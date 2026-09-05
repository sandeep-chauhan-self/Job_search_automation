import copy
import logging

import yaml

from src.llm.client import LLMClient

logger = logging.getLogger(__name__)

# Keys of the profile allowed to reach the resume. The rest of profile.yaml is agent
# metadata and only inflates the prompt.
RESUME_PROFILE_KEYS = (
    "personal",
    "headline",
    "summary",
    "impact_snapshot",
    "experience",
    "projects",
    "skills",
    "education",
    "certifications",
)

TAILOR_SYSTEM = """You are an expert resume writer specializing in ATS-optimized resumes. You tailor an EXISTING master resume to one specific job. You are an editor, not an author.

CRITICAL RULES:
1. ONLY use facts from the provided candidate profile. Do NOT fabricate metrics, employers, certifications, skills, projects, or achievements.
2. If the candidate lacks a skill the job requires, OMIT it. Do NOT invent experience.
3. PRESERVE EVERYTHING. Every section, employer, project and bullet in the profile must appear in your output. You may reorder and rephrase. You may NOT delete, merge, or summarize bullets away.
4. Return exactly the number of bullets per role and per project that the required output shape specifies.
5. Within each role, order bullets so the most job-relevant appear first.
6. Inject exact keywords from the job description into bullets ONLY where the candidate genuinely has that experience.
7. Keep every bullet substantive: 20-35 words, one or two lines. Do NOT compress bullets into short fragments - specific detail is what makes this resume credible.
8. Keep all quantified results (percentages, counts, release numbers) exactly as given in the profile. Never round, inflate, or drop a number.
9. Skills: use the profile's category names verbatim and keep every item. Reorder items within a category so job-relevant ones lead.
10. Write a tailored professional summary of 3-4 sentences positioning the candidate for THIS role, built only from profile facts.
11. Return ONLY valid JSON. No markdown, no explanation outside the JSON."""

TAILOR_USER = """## Candidate Profile
{profile_yaml}

## Target Job
Title: {job_title}
Company: {company}
Description:
{job_description}

## Match Analysis
Strengths: {reasons}
Gaps: {gaps}

## Required output shape (do not deviate)
{shape_spec}

## Task
Tailor this candidate's resume for the target job.
Return JSON in exactly this format:
{{
  "headline": "Short role-positioning line, pipe-separated",
  "summary": "Tailored 3-4 sentence professional summary",
  "impact_snapshot": ["Headline achievement 1", "Headline achievement 2"],
  "experience": [
    {{
      "title": "Exact title from profile",
      "company": "Exact company from profile",
      "bullets": ["Tailored bullet", "Tailored bullet", "..."]
    }}
  ],
  "projects": [
    {{
      "name": "Exact project name from profile",
      "bullets": ["Tailored bullet", "Tailored bullet", "..."]
    }}
  ],
  "skills": {{
    "Exact category name from profile": ["item", "item"]
  }}
}}

IMPORTANT: Keep ALL experience, project and skill entries from the profile. Only rewrite and reorder. Do NOT remove or add employers, projects, or skills."""

COVER_LETTER_SYSTEM = """You are a professional cover letter writer. Write concise, genuine cover letters.

RULES:
1. ONLY use facts from the candidate's profile. Do NOT fabricate.
2. 3 paragraphs max: (1) Why interested, (2) Most relevant experience, (3) Closing.
3. Keep it under 250 words.
4. Sound human, not robotic.
5. Return plain text only. No markdown, no JSON."""

COVER_LETTER_USER = """## Candidate Profile
{profile_yaml}

## Target Job
Title: {job_title}
Company: {company}
Description:
{short_desc}

## Task
Write a cover letter for this candidate applying to this role. 3 paragraphs, under 250 words."""

class ResumeTailor:
    def __init__(self, llm_client: LLMClient, profile: dict):
        self.llm = llm_client
        self.profile = profile or {}
        self.base = self._build_base()
        self.profile_yaml = yaml.dump(
            {k: self.profile[k] for k in RESUME_PROFILE_KEYS if k in self.profile},
            sort_keys=False,
            allow_unicode=True,
        )

    # -- profile normalization ------------------------------------------------

    def _build_base(self) -> dict:
        """Full profile shaped for the template. This is the floor: tailoring may improve
        on it, but the guard never lets output fall below it."""
        profile = self.profile
        personal = profile.get("personal") or {}
        skills = profile.get("skills") or {}
        return {
            "name": personal.get("name", ""),
            "email": personal.get("email", ""),
            "phone": personal.get("phone", ""),
            "location": personal.get("location", ""),
            "linkedin_url": personal.get("linkedin_url", ""),
            "github_url": personal.get("github_url", ""),
            "portfolio_url": personal.get("portfolio_url", ""),
            "headline": str(profile.get("headline", "") or "").strip(),
            "summary": str(profile.get("summary", "") or "").strip(),
            "impact_snapshot": self._clean_list(profile.get("impact_snapshot")),
            "experience": [self._base_role(r) for r in (profile.get("experience") or [])],
            "projects": [self._base_project(p) for p in (profile.get("projects") or [])],
            "skills": {str(k): self._clean_list(v) for k, v in skills.items()},
            "education": list(profile.get("education") or []),
            "certifications": self._clean_list(profile.get("certifications")),
        }

    @staticmethod
    def _clean_list(value) -> list:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _derive_dates(role: dict) -> str:
        start = str(role.get("start_date", "") or "").strip()
        end = str(role.get("end_date", "") or "").strip()
        return f"{start} - {end}".strip(" -")

    @classmethod
    def _base_role(cls, role: dict) -> dict:
        return {
            "title": role.get("title", ""),
            "company": role.get("company", ""),
            "location": role.get("location", ""),
            "dates": role.get("dates") or cls._derive_dates(role),
            "bullets": cls._clean_list(role.get("bullets")),
        }

    @classmethod
    def _base_project(cls, project: dict) -> dict:
        bullets = cls._clean_list(project.get("bullets"))
        if not bullets and project.get("description"):
            bullets = [str(project["description"]).strip()]
        return {
            "name": project.get("name", ""),
            "tech_stack": project.get("tech_stack", ""),
            "bullets": bullets,
        }

    def _shape_spec(self) -> str:
        lines = [f"- experience: exactly {len(self.base['experience'])} entries, in this order:"]
        for index, role in enumerate(self.base["experience"], 1):
            lines.append(
                f'  {index}. "{role["title"]}" at "{role["company"]}"'
                f' -> exactly {len(role["bullets"])} bullets'
            )
        lines.append(f"- projects: exactly {len(self.base['projects'])} entries, in this order:")
        for index, project in enumerate(self.base["projects"], 1):
            lines.append(f'  {index}. "{project["name"]}" -> exactly {len(project["bullets"])} bullets')
        lines.append(f"- impact_snapshot: exactly {len(self.base['impact_snapshot'])} bullets")
        lines.append("- skills: use these exact category names, keep every item, reorder only:")
        for category, items in self.base["skills"].items():
            lines.append(f'  "{category}" -> exactly {len(items)} items')
        return "\n".join(lines)

    # -- preservation guard ---------------------------------------------------

    def _keep_text(self, candidate, fallback: str, label: str, dropped: list) -> str:
        value = str(candidate).strip() if candidate else ""
        if not value:
            dropped.append(label)
            return fallback
        return value

    def _keep_list(self, candidate, fallback: list, label: str, dropped: list) -> list:
        items = self._clean_list(candidate)
        if len(items) < len(fallback):
            dropped.append(f"{label} ({len(items)}/{len(fallback)})")
            return list(fallback)
        return items

    @staticmethod
    def _match_entry(entries: list, base_entry: dict, index: int, key_fields: tuple) -> dict:
        key = tuple(str(base_entry.get(f, "")).strip().lower() for f in key_fields)
        for entry in entries:
            if isinstance(entry, dict) and key == tuple(
                str(entry.get(f, "")).strip().lower() for f in key_fields
            ):
                return entry
        if index < len(entries) and isinstance(entries[index], dict):
            return entries[index]
        return {}

    def _merge_entries(
        self, candidate, base_entries: list, key_fields: tuple, label: str, dropped: list
    ) -> list:
        entries = candidate if isinstance(candidate, list) else []
        if len(entries) != len(base_entries):
            dropped.append(f"{label} entries ({len(entries)}/{len(base_entries)})")

        merged = []
        for index, base_entry in enumerate(base_entries):
            entry = self._match_entry(entries, base_entry, index, key_fields)
            # Identity fields always come from the profile; the model may not rewrite them.
            result = dict(base_entry)
            result["bullets"] = self._keep_list(
                entry.get("bullets"), base_entry["bullets"], f"{label}[{index}].bullets", dropped
            )
            merged.append(result)
        return merged

    def _merge_skills(self, candidate, dropped: list) -> dict:
        proposed = candidate if isinstance(candidate, dict) else {}
        by_lower = {str(k).strip().lower(): v for k, v in proposed.items()}

        merged = {}
        for category, base_items in self.base["skills"].items():
            allowed = {item.lower(): item for item in base_items}
            ordered, seen = [], set()
            for item in self._clean_list(by_lower.get(category.strip().lower())):
                key = item.lower()
                if key in allowed and key not in seen:
                    seen.add(key)
                    ordered.append(allowed[key])
            if len(ordered) < len(base_items):
                dropped.append(f"skills[{category}] ({len(ordered)}/{len(base_items)})")
            # Reordering is allowed; losing or inventing an item is not.
            merged[category] = ordered + [i for i in base_items if i.lower() not in seen]
        return merged

    def _merge(self, response) -> dict:
        merged = copy.deepcopy(self.base)
        if not isinstance(response, dict):
            logger.warning(
                "Tailoring returned %s instead of a dict; falling back to the untailored profile.",
                type(response).__name__,
            )
            return merged

        dropped: list = []
        merged["headline"] = self._keep_text(
            response.get("headline"), self.base["headline"], "headline", dropped
        )
        merged["summary"] = self._keep_text(
            response.get("summary"), self.base["summary"], "summary", dropped
        )
        merged["impact_snapshot"] = self._keep_list(
            response.get("impact_snapshot"), self.base["impact_snapshot"], "impact_snapshot", dropped
        )
        merged["experience"] = self._merge_entries(
            response.get("experience"), self.base["experience"], ("company", "title"), "experience", dropped
        )
        merged["projects"] = self._merge_entries(
            response.get("projects"), self.base["projects"], ("name",), "projects", dropped
        )
        merged["skills"] = self._merge_skills(response.get("skills"), dropped)

        if dropped:
            logger.warning("Tailoring dropped content; restored from profile: %s", "; ".join(dropped))
        return merged

    # -- public ---------------------------------------------------------------

    def tailor_for_job(self, job: dict, job_id: str, run_id: str) -> dict:
        user_prompt = TAILOR_USER.format(
            profile_yaml=self.profile_yaml,
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", ""),
            reasons=job.get("match_reasons", "[]"),
            gaps=job.get("match_gaps", "[]"),
            shape_spec=self._shape_spec(),
        )
        
        response = self.llm.complete(
            prompt=user_prompt,
            system_prompt=TAILOR_SYSTEM,
            response_format="json",
            purpose="tailoring_resume",
            job_id=job_id,
            run_id=run_id
        )
        
        return self._merge(response)

    def should_generate_cover_letter(self, job_description: str) -> bool:
        """Simple keyword check: returns True if JD contains 'cover letter' (case-insensitive)."""
        if not job_description:
            return False
        return "cover letter" in job_description.lower()

    def generate_cover_letter(self, job: dict, job_id: str, run_id: str) -> str:
        desc = job.get("description", "")
        short_desc = desc[:1000] if desc else ""
        
        user_prompt = COVER_LETTER_USER.format(
            profile_yaml=self.profile_yaml,
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            short_desc=short_desc
        )
        
        response = self.llm.complete(
            prompt=user_prompt,
            system_prompt=COVER_LETTER_SYSTEM,
            response_format="text",
            purpose="tailoring_cover_letter",
            job_id=job_id,
            run_id=run_id
        )
        return str(response)
