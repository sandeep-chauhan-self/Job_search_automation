import pytest
from src.auto_applier.question_answerer import QuestionAnswerer

class MockLLM:
    def complete(self, prompt, **kwargs):
        if "React" in prompt:
            return "4"
        return "I don't know"

def test_question_answerer():
    answers = [{"pattern": "years of experience", "answer": "6"}]
    profile = {"personal": {"name": "Test"}}
    
    qa = QuestionAnswerer(MockLLM(), answers, profile)
    
    # Tier 1 match
    assert qa.get_answer("How many years of experience?", "text") == "6"
    
    # Tier 2 LLM fallback
    assert qa.get_answer("Years of React?", "number") == "4"
