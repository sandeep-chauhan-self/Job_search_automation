import litellm
import json
import logging
from src.database.models import LLMUsage

class LLMResponseError(Exception):
    pass

class LLMClient:
    def __init__(self, db_session, config: dict, secrets: dict):
        self.db = db_session
        self.config = config.get("llm", {})
        self.api_key = secrets.get("llm_api_key")
        
        # Configure LiteLLM
        if self.api_key and self.api_key != "your-api-key-here":
            litellm.api_key = self.api_key
            
        litellm.suppress_debug_info = True

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: str = "json",
        max_retries: int = 2,
        purpose: str = "general",
        job_id: str = None,
        run_id: str = None
    ) -> dict | str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        retries = 0
        last_error = None
        
        while retries <= max_retries:
            try:
                response = self._call_litellm(messages, response_format)
                content = response.choices[0].message.content
                
                self._log_usage(response, purpose, job_id, run_id)
                
                if response_format == "json":
                    try:
                        return self._parse_json_robustly(content)
                    except ValueError as e:
                        last_error = e
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": "Your previous response was invalid JSON. Please fix it and return ONLY valid JSON."})
                        retries += 1
                        continue
                
                return content
            except Exception as e:
                last_error = e
                retries += 1
                
        raise LLMResponseError(f"Failed after {max_retries} retries. Last error: {last_error}")

    def _call_litellm(self, messages: list[dict], response_format: str):
        model = self.config.get("provider", "gpt-4o-mini")
        temperature = self.config.get("temperature", 0.3)
        max_tokens = self.config.get("max_tokens", 2000)
        
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        if response_format == "json" and not model.startswith("ollama"):
            kwargs["response_format"] = {"type": "json_object"}
            
        return litellm.completion(**kwargs)

    def _parse_json_robustly(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

    def _log_usage(self, response, purpose: str, job_id: str, run_id: str):
        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception:
            cost = 0.0
            
        usage = getattr(response, "usage", None)
        if usage:
            input_tokens = getattr(usage, "prompt_tokens", 0)
            output_tokens = getattr(usage, "completion_tokens", 0)
        else:
            input_tokens = 0
            output_tokens = 0
            
        llm_usage = LLMUsage(
            run_id=run_id,
            job_id=job_id,
            purpose=purpose,
            model=getattr(response, "model", "unknown"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost or 0.0
        )
        self.db.add(llm_usage)
        self.db.commit()
