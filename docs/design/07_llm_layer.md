# Module 07: LLM Integration Layer

> **Depends on:** `00_shared_contracts.md`
> **Files to create:** `src/llm/__init__.py`, `src/llm/client.py`, `src/llm/cost_tracker.py`
> **External dependency:** LiteLLM
> **LLM required:** Yes (this IS the LLM integration)
> **Estimated effort:** Small

---

## Purpose

Provide a single, unified abstraction layer for all LLM calls in the system. By routing all calls through this module, we can easily swap providers (OpenAI, DeepSeek, Ollama), track costs centrally, and handle API retries and JSON validation robustly without duplicating code in the scoring, tailoring, or applier modules.

---

## Input

- `config/config.yaml` — `llm.provider`, `llm.temperature`, `llm.max_tokens`
- `config/secrets.yaml` — `llm_api_key`

## Output

- Standardized string or JSON responses to calling modules
- Updated `llm_usage` rows in the database (token counts, cost)

---

## File: `src/llm/client.py`

### Class: `LLMClient`

```python
import litellm
import json
import logging

class LLMResponseError(Exception):
    pass

class LLMClient:
    def __init__(self, db_session, config: dict, secrets: dict):
        self.db = db_session
        self.config = config["llm"]
        self.api_key = secrets.get("llm_api_key")
        
        # Configure LiteLLM
        litellm.api_key = self.api_key
        # Silence litellm verbose logging
        litellm.suppress_debug_info = True

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: str = "json",  # "json" or "text"
        max_retries: int = 2,
        purpose: str = "general",
        job_id: str = None,
        run_id: str = None
    ) -> dict | str:
        """
        Send a prompt to the configured LLM provider via LiteLLM.
        """
        ...

    def _call_litellm(self, messages: list[dict], response_format: str) -> litellm.ModelResponse:
        """Wrapper around litellm.completion with exponential backoff."""
        ...

    def _parse_json_robustly(self, content: str) -> dict:
        """
        Handle common LLM JSON formatting errors.
        - Strip markdown code blocks (```json ... ```)
        - Fix trailing commas
        - If parsing fails, raise ValueError
        """
        ...

    def _log_usage(self, response: litellm.ModelResponse, purpose: str, 
                   job_id: str, run_id: str):
        """
        Calculate cost and insert into llm_usage table.
        """
        ...
```

---

## JSON Validation & Retry Strategy

When `response_format="json"`:
1. Instruct the LLM in the system prompt to return ONLY valid JSON.
2. If the LLM returns text with markdown blocks (e.g., ````json { ... } ````), strip them.
3. Parse with `json.loads()`.
4. If `json.loads()` throws `JSONDecodeError`, retry the call (up to `max_retries`).
5. On the retry prompt, optionally append: `"Your previous response was invalid JSON. Please fix it and return ONLY valid JSON."`
6. If retries are exhausted, raise `LLMResponseError`. The calling module (e.g., Scoring Engine) must catch this and skip the job.

---

## Cost Tracking

LiteLLM provides cost tracking out of the box. Use `litellm.completion_cost(response)` to get the USD cost of the call.

Insert into the `llm_usage` table:
- `run_id`, `job_id`, `purpose` (e.g., "scoring", "tailoring", "qa")
- `model` (e.g., "gpt-4o-mini")
- `input_tokens`, `output_tokens`
- `cost_usd`

---

## Handling Local LLMs (Ollama)

If `config["llm"]["provider"]` starts with `"ollama/"`:
- LiteLLM handles this automatically if Ollama is running locally on port 11434.
- No API key is needed.
- Set cost to `0.0` explicitly if LiteLLM doesn't.

---

## File: `src/llm/cost_tracker.py`

### Class: `CostTracker`

```python
class CostTracker:
    def __init__(self, db_session):
        self.db = db_session

    def get_run_cost(self, run_id: str) -> float:
        """SUM(cost_usd) from llm_usage WHERE run_id = ?"""
        ...

    def get_job_cost(self, job_id: str) -> float:
        """SUM(cost_usd) from llm_usage WHERE job_id = ?"""
        ...

    def get_total_cost(self) -> float:
        """Total spent across all runs"""
        ...
```

---

## Error Handling

- API Key Missing → Raise configuration error on initialization.
- Provider down / Rate Limit → Handled by exponential backoff. If max retries reached, raise exception.
- Context length exceeded (JD too long) → Truncate JD to `config["llm"]["max_tokens"] - 500` before calling, or catch `ContextWindowExceededError` and retry with truncation.

---

## Test Scenarios (`tests/test_llm_client.py`)

1. **Test basic completion (mocked):** Verify Litellm is called with correct model and temperature.
2. **Test JSON parsing:** Pass a mocked response with ````json ... ```` formatting and ensure it is parsed correctly.
3. **Test JSON retry:** Mock `json.loads` to fail once, then succeed. Verify `litellm.completion` is called twice.
4. **Test usage logging:** Verify a successful call inserts a row into `llm_usage` with correct token counts and calculated cost.
5. **Test Ollama fallback:** If Ollama is configured, verify no API key error is thrown and cost is $0.00.
