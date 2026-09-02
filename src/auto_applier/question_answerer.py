import os
import yaml
from datetime import datetime
from src.llm.client import LLMClient

class QuestionAnswerer:
    def __init__(self, llm_client: LLMClient, answers: list[dict], profile: dict):
        self.llm = llm_client
        self.answers = answers
        self.profile = profile
        self.log_path = "output/logs/new_questions.log"
        self.profile_yaml = yaml.dump(profile, sort_keys=False)

    def get_answer(self, question_text: str, field_type: str, options: list[str] = None) -> str:
        # Tier 1: Local lookup
        answer = self._lookup_answer(question_text)
        if answer is not None:
            return answer
            
        # Tier 2: LLM Fallback
        answer = self._ask_llm(question_text, field_type, options)
        self._log_new_question(question_text, answer)
        return answer

    def _lookup_answer(self, question_text: str) -> str | None:
        if not question_text:
            return None
        q_lower = question_text.lower()
        for entry in self.answers:
            if entry.get("pattern", "").lower() in q_lower:
                return str(entry.get("answer"))
        return None

    def _ask_llm(self, question_text: str, field_type: str, options: list[str] = None) -> str:
        system_prompt = "You are answering a job application form question. Be concise and direct."
        
        user_prompt = f"Candidate Profile:\n{self.profile_yaml}\n\nQuestion: \"{question_text}\"\nField type: {field_type}\n"
        if options:
            user_prompt += f"Available options: {options}\n"
            
        user_prompt += """
Rules:
1. Answer ONLY from the candidate's actual profile. Do NOT fabricate.
2. Be concise. For number fields, return just the number. For text, 1-2 sentences max.
3. If the question asks about a skill the candidate doesn't have, answer honestly (e.g. 0).
4. Return ONLY the answer text. No explanation, no quotes, no formatting.
"""
        try:
            res = self.llm.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                response_format="text",
                purpose="qa_fallback"
            )
            return str(res).strip()
        except Exception:
            return ""

    def _log_new_question(self, question: str, answer: str):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Q: {question}\n")
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] A: {answer}\n")
            f.write("---\n")
