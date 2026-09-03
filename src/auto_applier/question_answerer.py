import logging
import os
import re
from datetime import datetime

import yaml

from src.llm.client import LLMClient
from src.settings import OUTPUT_DIR

# Words that are capitalised for grammar, not because they name a technology.
_CAPITALISED_STOPWORDS = {
    "how", "what", "why", "when", "where", "which", "who", "do", "does", "did",
    "are", "is", "was", "were", "have", "has", "had", "can", "could", "would",
    "will", "should", "the", "this", "that", "your", "you", "we", "our", "i",
    "if", "in", "on", "at", "of", "for", "to", "and", "or", "a", "an", "please",
    "yes", "no", "years", "year", "experience", "salary", "notice", "period",
    "total", "current", "expected", "many", "much", "do", "you",
}

# A qualifier clause turns a generic question into a specific one.
_QUALIFIER = re.compile(r"\b(?:with|in|using|for)\s+([A-Za-z][A-Za-z0-9+#.\- ]{1,40})", re.I)


class QuestionAnswerer:
    """Two-tier answering: your saved answers first, grounded LLM second.

    Saved answers are submitted verbatim to real employers, so matching has to
    be conservative. A generic saved answer must never be used to answer a
    question about a specific technology.
    """

    def __init__(self, llm_client: LLMClient, answers: list[dict], profile: dict):
        self.llm = llm_client
        self.answers = answers or []
        self.profile = profile or {}
        self.log_path = os.path.join(OUTPUT_DIR, "logs", "new_questions.log")
        self.profile_yaml = yaml.dump(profile, sort_keys=False)
        self.audit: list[dict] = []
        self._skill_vocab = self._build_skill_vocab()

    def _build_skill_vocab(self) -> set[str]:
        vocab: set[str] = set()
        skills = self.profile.get("skills", {}) or {}
        for group in skills.values():
            if isinstance(group, list):
                vocab.update(str(s).strip().lower() for s in group if str(s).strip())
        return vocab

    # -- public ---------------------------------------------------------------

    def get_answer(self, question_text: str, field_type: str, options: list[str] = None) -> str:
        saved = self._lookup_answer(question_text)
        if saved is not None:
            self._record(question_text, saved, "saved")
            return saved

        answer = self._ask_llm(question_text, field_type, options)
        self._record(question_text, answer, "llm")
        self._log_new_question(question_text, answer)
        return answer

    def _record(self, question: str, answer: str, source: str) -> None:
        self.audit.append({"question": question, "answer": answer, "source": source})

    # -- tier 1: saved answers ------------------------------------------------

    def _lookup_answer(self, question_text: str) -> str | None:
        if not question_text:
            return None
        q_lower = question_text.lower()

        # Longest pattern first so a specific entry beats a generic one.
        candidates = sorted(
            self.answers, key=lambda e: len(str(e.get("pattern", ""))), reverse=True
        )

        for entry in candidates:
            pattern = str(entry.get("pattern", "")).strip().lower()
            if not pattern or pattern not in q_lower:
                continue

            excludes = [str(x).lower() for x in (entry.get("exclude_if_contains") or [])]
            if any(x in q_lower for x in excludes):
                logging.info("Saved answer for %r skipped: excluded term present.", pattern)
                continue

            if entry.get("generic") and self._names_specific_subject(question_text, pattern):
                logging.info(
                    "Generic answer for %r skipped: question names a specific subject.", pattern
                )
                continue

            return str(entry.get("answer"))
        return None

    def _names_specific_subject(self, question: str, pattern: str) -> bool:
        """True when the question is about a named technology, tool, or company.

        Answering "6 years" to "years of experience with Kubernetes" would state
        something false to an employer, so those questions must fall through to
        the profile-grounded path instead.
        """
        remainder = re.sub(re.escape(pattern), " ", question, flags=re.I)

        for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", remainder):
            low = token.lower()
            if low in _CAPITALISED_STOPWORDS:
                continue
            if low in self._skill_vocab:
                return True
            # Mid-sentence capitals and acronyms almost always name a product.
            if token[0].isupper() or token.isupper():
                return True

        match = _QUALIFIER.search(remainder)
        if match and match.group(1).strip().lower() not in _CAPITALISED_STOPWORDS:
            return True
        return False

    # -- tier 2: grounded LLM -------------------------------------------------

    def _ask_llm(self, question_text: str, field_type: str, options: list[str] = None) -> str:
        system_prompt = (
            "You are filling in a job application form on behalf of a candidate. "
            "Answer ONLY from the candidate profile provided. Never invent experience, "
            "skills, dates, or numbers. A false answer here goes to a real employer."
        )

        user_prompt = f"Candidate Profile:\n{self.profile_yaml}\n\nQuestion: \"{question_text}\"\nField type: {field_type}\n"
        if options:
            user_prompt += f"Available options: {options}\n"

        user_prompt += """
Rules:
1. Answer ONLY from the candidate's actual profile. Do NOT fabricate.
2. Be concise. For number fields, return just the number. For text, 1-2 sentences max.
3. If the question asks about a skill the candidate does not have, answer honestly (0 or No).
4. Return ONLY the answer text. No explanation, no quotes, no formatting.
"""
        try:
            res = self.llm.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                response_format="text",
                purpose="qa_fallback",
            )
            return str(res).strip()
        except Exception as exc:
            # Better to leave a field blank and get queued for manual review
            # than to guess at something that gets submitted.
            logging.error("Could not answer %r: %s", question_text, exc)
            return ""

    def _log_new_question(self, question: str, answer: str):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] Q: {question}\n")
            f.write(f"[{stamp}] A: {answer}\n")
            f.write("---\n")
