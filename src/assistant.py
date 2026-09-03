"""Grounded Q&A over your profile and job corpus.

Anti-hallucination design: the model only ever sees facts assembled here, is
told to refuse rather than guess, and every answer returns the sources used so
claims can be checked against the underlying data.
"""

import json
import logging

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session

from src import constants as C
from src.database.models import Document, Interview, Job

SYSTEM_PROMPT = """You answer questions about ONE specific job seeker using ONLY the facts provided below.

ABSOLUTE RULES:
1. Use ONLY information in the CONTEXT section. It is the complete set of facts available to you.
2. NEVER invent employers, dates, titles, skills, metrics, salaries, or job details. If a specific
   number, date, or name is not in the CONTEXT, you do not know it.
3. If the CONTEXT does not contain the answer, reply exactly: "That is not in your profile or job
   data." Then state what information would be needed. Do NOT guess or fill gaps with plausible detail.
4. Do not infer skills the candidate did not list. Adjacent experience is not the same as the skill.
5. When you state a fact, cite its source tag in square brackets, e.g. [profile.experience] or [jobs.applied].
6. Be concise and direct. No preamble.

You are helping the candidate understand their own profile and job search. Accuracy matters far more
than sounding helpful - a wrong detail could end up in a real job application."""


class ProfileAssistant:
    def __init__(self, db: Session, llm_client, profile: dict):
        self.db = db
        self.llm = llm_client
        self.profile = profile or {}

    # -- context assembly ----------------------------------------------------

    def _profile_context(self) -> str:
        if not self.profile:
            return "[profile] EMPTY - the candidate has not filled in config/profile.yaml."
        return "[profile]\n" + yaml.dump(self.profile, sort_keys=False, allow_unicode=True)

    def _corpus_context(self) -> str:
        db = self.db
        total = db.query(Job).count()
        if total == 0:
            return "[jobs] No jobs discovered yet."

        by_status = dict(db.query(Job.status, func.count(Job.id)).group_by(Job.status).all())
        applied = (
            db.query(Job)
            .filter(Job.applied_at.isnot(None))
            .order_by(Job.applied_at.desc())
            .limit(40)
            .all()
        )
        top_matches = (
            db.query(Job)
            .filter(Job.match_score.isnot(None))
            .order_by(Job.match_score.desc())
            .limit(15)
            .all()
        )
        interviews = (
            db.query(Interview).order_by(Interview.scheduled_at.desc().nullslast()).limit(20).all()
        )
        doc_count = db.query(Document).count()

        lines = [
            "[jobs.summary]",
            f"Total jobs in corpus: {total}",
            f"Counts by status: {json.dumps(by_status)}",
            f"Tailored documents generated: {doc_count}",
            "",
            "[jobs.applied] Applications submitted (most recent first):",
        ]
        lines += [
            f"- {j.title} @ {j.company} | applied {j.applied_at:%Y-%m-%d} | status {j.status}"
            f" | score {j.match_score if j.match_score is not None else 'n/a'}"
            for j in applied
        ] or ["- none"]

        lines += ["", "[jobs.top_matches] Highest scoring matches:"]
        lines += [
            f"- {j.title} @ {j.company} | score {j.match_score} | status {j.status}"
            for j in top_matches
        ] or ["- none"]

        if interviews:
            lines += ["", "[jobs.interviews]"]
            for iv in interviews:
                job = db.query(Job).filter(Job.id == iv.job_id).first()
                when = f"{iv.scheduled_at:%Y-%m-%d %H:%M}" if iv.scheduled_at else "unscheduled"
                lines.append(
                    f"- {iv.round_name} @ {job.company if job else 'unknown'} | {when} | {iv.outcome}"
                )

        return "\n".join(lines)

    def build_context(self) -> str:
        return f"{self._profile_context()}\n\n{self._corpus_context()}"

    # -- public API ----------------------------------------------------------

    def ask(self, question: str) -> dict:
        context = self.build_context()
        prompt = (
            f"CONTEXT\n=======\n{context}\n\n"
            f"=======\nQUESTION: {question}\n\n"
            "Answer using only the CONTEXT above. Cite source tags in square brackets."
        )

        try:
            answer = self.llm.complete(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                response_format="text",
                purpose="profile_qa",
            )
        except Exception as exc:
            logging.error("Profile Q&A failed: %s", exc)
            return {
                "answer": None,
                "error": str(exc),
                "grounded_on": self._source_tags(),
            }

        return {
            "answer": str(answer).strip(),
            "error": None,
            "grounded_on": self._source_tags(),
        }

    def _source_tags(self) -> list[str]:
        tags = ["profile"]
        if self.db.query(Job).count():
            tags += ["jobs.summary", "jobs.applied", "jobs.top_matches"]
        if self.db.query(Interview).count():
            tags.append("jobs.interviews")
        return tags

    def profile_completeness(self) -> dict:
        """Missing profile data is the main cause of bad matches and weak resumes."""
        personal = self.profile.get("personal", {}) or {}
        checks = {
            "name": bool(personal.get("name")) and personal.get("name") != "John Doe",
            "email": bool(personal.get("email")) and "example.com" not in str(personal.get("email", "")),
            "phone": bool(personal.get("phone")),
            "location": bool(personal.get("location")),
            "linkedin": bool(personal.get("linkedin_url")),
            "summary": bool(self.profile.get("summary")),
            "experience": bool(self.profile.get("experience")),
            "skills": bool(self.profile.get("skills")),
            "education": bool(self.profile.get("education")),
            "preferences": bool(self.profile.get("preferences")),
        }
        missing = [k for k, ok in checks.items() if not ok]
        return {
            "score": round(100 * sum(checks.values()) / len(checks)),
            "checks": checks,
            "missing": missing,
            "is_placeholder": personal.get("name") == "John Doe",
        }
