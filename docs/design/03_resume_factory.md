# Module 03: Resume Factory

> **Depends on:** `00_shared_contracts.md`, `07_llm_layer.md`
> **Files to create:** `src/resume_factory/__init__.py`, `src/resume_factory/tailoring.py`, `src/resume_factory/renderer.py`, `templates/resume_template.html`, `templates/resume_styles.css`, `templates/cover_letter_template.html`
> **External dependencies:** LLM client, Jinja2, Playwright (for PDF)
> **LLM required:** Yes
> **Estimated effort:** Medium (includes HTML template design)

---

## Purpose

For each job with `status = "SCORED"`, use the LLM to tailor the user's resume content for that specific job, render it into a beautiful ATS-safe HTML template, and export as PDF via Playwright.

---

## Input

- DB: All jobs where `status = "SCORED"` (above threshold)
- `config/profile.yaml` — user's master profile
- `templates/resume_template.html` + `resume_styles.css` — HTML/CSS template
- Job's `match_reasons` and `match_gaps` from scoring step

## Output

- PDF file: `output/resumes/{job_id}_{company_slug}_resume.pdf`
- Optional PDF: `output/cover_letters/{job_id}_{company_slug}_cover.pdf`
- Updated DB: `status` → `RESUME_READY`, `resume_path`, `cover_letter_path`, `resume_generated_at`

---

## Architecture

```
Profile YAML ──┐
               ├──→ LLM Tailoring Engine ──→ Tailored JSON ──→ Jinja2 + HTML Template ──→ Playwright PDF
Job Description┘                                                                            ↓
                                                                                    output/resumes/{id}.pdf
```

---

## File: `src/resume_factory/tailoring.py`

### Class: `ResumeTailor`

```python
class ResumeTailor:
    def __init__(self, llm_client: LLMClient, profile: dict):
        self.llm = llm_client
        self.profile = profile

    def tailor_for_job(self, job: dict) -> dict:
        """
        Takes a job dict (title, company, description, match_reasons, match_gaps).
        Returns a tailored resume content dict ready for template rendering.
        
        Output format:
        {
            "name": "John Doe",
            "email": "...",
            "phone": "...",
            "linkedin_url": "...",
            "github_url": "...",
            "portfolio_url": "...",
            "summary": "Tailored 2-3 sentence summary for THIS job",
            "experience": [
                {
                    "title": "Senior Software Engineer",
                    "company": "TechCorp",
                    "location": "Bangalore",
                    "dates": "Jan 2022 - Present",
                    "bullets": [
                        "Tailored bullet emphasizing relevant skills...",
                        "Another tailored bullet..."
                    ]
                },
                ...
            ],
            "skills": {
                "languages": ["Python", "JavaScript", ...],
                "frameworks": ["React", "FastAPI", ...],
                "tools": ["Docker", "AWS", ...]
            },
            "education": [...],
            "certifications": [...]
        }
        """
        ...

    def should_generate_cover_letter(self, job_description: str) -> bool:
        """
        Simple keyword check: returns True if JD contains 
        'cover letter' (case-insensitive).
        """
        return "cover letter" in job_description.lower()

    def generate_cover_letter(self, job: dict) -> str:
        """
        Returns cover letter text (plain text, 3-4 paragraphs).
        """
        ...
```

---

## LLM Prompts (Exact Text)

### Resume Tailoring — System Prompt

```
You are an expert resume writer specializing in ATS-optimized resumes. You rewrite resume content to maximize relevance for specific job descriptions.

CRITICAL RULES:
1. ONLY use facts from the provided candidate profile. Do NOT fabricate metrics, employers, certifications, skills, or achievements.
2. If the candidate lacks a skill the job requires, OMIT it. Do NOT invent experience.
3. Reorder and rephrase existing bullet points to highlight relevance to THIS specific job.
4. Inject exact keywords from the job description into bullet points where the candidate genuinely has that experience.
5. Use strong action verbs (Led, Built, Designed, Implemented, Reduced, Increased).
6. Keep bullet points concise (1 line each, max 15 words).
7. Write a tailored professional summary (2-3 sentences) that positions the candidate for THIS specific role.
8. Return ONLY valid JSON. No markdown, no explanation outside the JSON.
```

### Resume Tailoring — User Prompt Template

```
## Candidate Profile
{profile_yaml_as_text}

## Target Job
Title: {job_title}
Company: {company}
Description:
{job_description}

## Match Analysis
Strengths: {match_reasons_as_list}
Gaps: {match_gaps_as_list}

## Task
Rewrite this candidate's resume content to be maximally relevant for the target job.
Return JSON in exactly this format:
{
  "summary": "Tailored 2-3 sentence professional summary",
  "experience": [
    {
      "title": "Exact title from profile",
      "company": "Exact company from profile",
      "location": "Exact location from profile",
      "dates": "Month Year - Month Year",
      "bullets": ["Tailored bullet 1", "Tailored bullet 2", "Tailored bullet 3"]
    }
  ],
  "skills": {
    "languages": ["..."],
    "frameworks": ["..."],
    "tools": ["..."]
  }
}

IMPORTANT: Keep ALL experience entries from the profile. Only rewrite bullets and reorder skills. Do NOT remove or add employers.
```

### Cover Letter — System Prompt

```
You are a professional cover letter writer. Write concise, genuine cover letters.

RULES:
1. ONLY use facts from the candidate's profile. Do NOT fabricate.
2. 3 paragraphs max: (1) Why you're interested in the role, (2) Your most relevant experience, (3) Closing.
3. Keep it under 250 words.
4. Sound human, not robotic. Show genuine enthusiasm without being generic.
5. Mention the company name and specific role.
6. Return plain text only. No markdown, no JSON.
```

### Cover Letter — User Prompt Template

```
## Candidate Profile
{profile_yaml_as_text}

## Target Job
Title: {job_title}
Company: {company}
Description (key requirements):
{first_500_chars_of_description}

## Task
Write a cover letter for this candidate applying to this role. 3 paragraphs, under 250 words.
```

---

## File: `src/resume_factory/renderer.py`

### Class: `ResumeRenderer`

```python
class ResumeRenderer:
    def __init__(self, template_dir: str = "templates", output_dir: str = "output"):
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))

    async def render_resume_pdf(self, tailored_content: dict, job_id: str, company: str) -> str:
        """
        1. Load resume_template.html
        2. Render with Jinja2 using tailored_content dict
        3. Launch Playwright (headless=True — PDF export doesn't need headed mode)
        4. page.set_content(rendered_html)
        5. page.pdf(path=output_path, format="A4", print_background=True)
        6. Return the output file path
        """
        ...

    async def render_cover_letter_pdf(self, cover_letter_text: str, personal_info: dict, 
                                       job_title: str, company: str, job_id: str) -> str:
        """
        Same flow as resume but with cover_letter_template.html.
        """
        ...

    def _slugify(self, text: str) -> str:
        """Convert company name to filesystem-safe slug: 'Tech Corp Inc' → 'tech_corp_inc'"""
        ...
```

---

## HTML Resume Template Design Requirements

**File:** `templates/resume_template.html` + `templates/resume_styles.css`

### Design Principles (ATS-safe + human-beautiful)

1. **Single-column layout** — no CSS grid columns, no floats for content blocks
2. **Semantic HTML** — use `<h1>` for name, `<h2>` for section headings, `<ul>/<li>` for bullets
3. **Standard section headings** — "Professional Summary", "Experience", "Skills", "Education"
4. **Modern typography** — use `@import` for Inter or Calibri font
5. **Clean spacing** — generous `line-height: 1.5`, `margin-bottom` between sections
6. **Subtle design touches** — thin top border accent color, slightly larger name, muted secondary text for dates/locations
7. **Print-optimized CSS** — include `@media print` rules for margins and page breaks
8. **ATS safety checks:**
   - NO images, icons, or SVG
   - NO CSS `columns` or `column-count`
   - NO `position: absolute` for content text
   - NO text in `::before` / `::after` pseudo-elements
   - Disable ligatures: `text-rendering: optimizeSpeed;`

### Template Variables (Jinja2)

```html
<!-- Available variables from tailored_content dict -->
{{ name }}
{{ email }}
{{ phone }}
{{ linkedin_url }}
{{ github_url }}
{{ portfolio_url }}
{{ summary }}

{% for job in experience %}
  {{ job.title }}
  {{ job.company }}
  {{ job.location }}
  {{ job.dates }}
  {% for bullet in job.bullets %}
    {{ bullet }}
  {% endfor %}
{% endfor %}

{% for category, items in skills.items() %}
  {{ category }}: {{ items | join(", ") }}
{% endfor %}

{% for edu in education %}
  {{ edu.degree }} — {{ edu.institution }} ({{ edu.year }})
{% endfor %}
```

---

## Error Handling

- LLM returns invalid JSON → retry once, then skip this job (status stays `SCORED` for next run)
- LLM fabricates a company not in profile → validation: compare `experience[].company` from LLM output against profile. If mismatch, reject and retry with stronger prompt
- Playwright PDF fails → log error, skip job, continue
- Template file missing → raise clear error at startup (fail fast)

---

## Test Scenarios (`tests/test_resume_factory.py`)

1. **Test tailoring prompt:** Verify profile and JD are correctly injected
2. **Test grounding:** Mock LLM returning a fabricated employer → verify it's caught and rejected
3. **Test cover letter decision:** JD containing "cover letter" → True, JD without → False
4. **Test Jinja2 rendering:** Pass a known tailored_content dict → verify HTML output contains expected text
5. **Test PDF generation:** Render a sample HTML → verify PDF file is created and non-empty
6. **Test file naming:** Verify output path matches `{job_id}_{company_slug}_resume.pdf` pattern
