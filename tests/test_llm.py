import pytest
from src.llm.client import LLMClient, LLMResponseError
from src.llm.cost_tracker import CostTracker
from src.database.connection import get_db
import litellm

class MockMessage:
    def __init__(self, content):
        self.content = content

class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)

class MockUsage:
    def __init__(self):
        self.prompt_tokens = 10
        self.completion_tokens = 20

class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(content)]
        self.usage = MockUsage()
        self.model = "mock-model"

def test_json_parsing_robustness():
    client = LLMClient(None, {}, {})
    
    # Clean JSON
    assert client._parse_json_robustly('{"key": "value"}') == {"key": "value"}
    
    # Markdown wrapped JSON
    assert client._parse_json_robustly('```json\n{"key": "value"}\n```') == {"key": "value"}
    
    # Invalid JSON
    with pytest.raises(ValueError):
        client._parse_json_robustly('{"key": "value"')

def test_completion_retry_logic(monkeypatch):
    db = get_db()
    
    client = LLMClient(db, {"llm": {"provider": "test"}}, {})
    
    responses = [
        MockResponse('Invalid JSON text'),
        MockResponse('{"valid": "json"}')
    ]
    
    def mock_call(*args, **kwargs):
        return responses.pop(0)
        
    monkeypatch.setattr(client, "_call_litellm", mock_call)
    monkeypatch.setattr(litellm, "completion_cost", lambda x: 0.01)
    
    # Should succeed on second try
    res = client.complete("test", response_format="json")
    assert res == {"valid": "json"}
    
    # Should fail if max retries reached
    responses = [MockResponse('Invalid JSON text')] * 4
    with pytest.raises(LLMResponseError):
        client.complete("test", response_format="json", max_retries=1)

def test_cost_tracker():
    db = get_db()
    
    tracker = CostTracker(db)
    # Just verify methods run without error since LLMUsage inserts are tested implicitly above
    assert isinstance(tracker.get_total_cost(), float)
