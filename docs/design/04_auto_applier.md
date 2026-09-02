# Module 04: Auto-Applier (LinkedIn Easy Apply)

> **Depends on:** `00_shared_contracts.md`, `07_llm_layer.md`
> **Files to create:** `src/auto_applier/__init__.py`, `src/auto_applier/applier.py`, `src/auto_applier/form_filler.py`, `src/auto_applier/question_answerer.py`
> **External dependency:** Playwright (headed mode), LLM client
> **LLM required:** Yes (for unknown questions only)
> **Estimated effort:** Large (most complex module — interacts with live UI)

---

## Purpose

For LinkedIn Easy Apply jobs with `status = "RESUME_READY"`, automate the entire application flow: open job page → click Easy Apply → fill form fields → upload tailored resume → answer questions → submit.

Jobs go through a **"Review & Launch"** step first where the user can veto jobs before submission.

---

## Input

- DB: Jobs where `status = "RESUME_READY"` AND `platform = "linkedin"`
- `config/answers.yaml` — pre-saved Q&A pairs
- `config/profile.yaml` — for LLM fallback answers
- `config/config.yaml` — daily limits, delay settings, browser viewport
- Generated resume PDF from `output/resumes/`

## Output

- Updated DB: `status` → `APPLIED` (or `QUEUED_FOR_MANUAL` on failure), `applied_at`, `applied_method = "auto"`
- Screenshot: `output/screenshots/{job_id}_submitted.png`
- New Q&A log: `output/logs/new_questions.log` (questions the LLM had to answer)
- `llm_usage` rows for any LLM calls made

---

## Flow

```
RESUME_READY (LinkedIn) jobs
        ↓
[Dashboard: "Review & Launch" batch list]
  User unchecks any jobs they don't want
  User clicks "Apply All"
        ↓
For each approved job:
  1. Open job URL in Playwright (headed, non-headless)
  2. Click "Easy Apply" button
  3. For each form page:
     a. Detect all form fields (text, dropdown, radio, checkbox, file upload)
     b. For file upload → attach tailored resume PDF
     c. For each question:
        i.  Check answers.yaml (substring match on question text)
        ii. If found → use pre-saved answer
        iii. If not found → send to LLM for generated answer → log to new_questions.log
     d. Click "Next" or "Review" or "Submit"
  4. On final page → click "Submit application"
  5. Take screenshot
  6. Update DB: status = APPLIED
  7. Wait random delay (3-8 seconds)
        ↓
If daily_limit reached → stop
If error on a job → status = QUEUED_FOR_MANUAL, continue to next
```

---

## File: `src/auto_applier/applier.py`

### Class: `AutoApplier`

```python
class AutoApplier:
    def __init__(self, db_session, llm_client: LLMClient, config: dict, 
                 profile: dict, answers: list[dict]):
        self.db = db_session
        self.llm = llm_client
        self.config = config
        self.profile = profile
        self.form_filler = FormFiller(answers, profile)
        self.qa = QuestionAnswerer(llm_client, answers, profile)
        self.daily_limit = config["application"]["daily_limit"]
        self.delay_min = config["application"]["delay_min_seconds"]
        self.delay_max = config["application"]["delay_max_seconds"]
        self.viewport = config["application"]["browser_viewport"]

    async def run(self, run_id: str, approved_job_ids: list[str]) -> dict:
        """
        Apply to approved LinkedIn Easy Apply jobs.
        Returns: {"applied": N, "failed": M, "skipped_limit": K}
        
        Steps:
        1. Launch Playwright browser (headed=True, persistent context with cookies)
        2. Check if LinkedIn is logged in. If not, prompt user via dashboard.
        3. For each approved job_id (up to daily_limit):
           a. Navigate to job_url
           b. Call _apply_to_job()
           c. On success: update status to APPLIED
           d. On failure: update status to QUEUED_FOR_MANUAL, log error
           e. Random delay between delay_min and delay_max
        4. Close browser
        5. Update runs table
        """
        ...

    async def _apply_to_job(self, page, job: dict) -> bool:
        """
        Handle the full Easy Apply flow for one job.
        Returns True on success, False on failure.
        
        Steps:
        1. Click "Easy Apply" button (wait for modal)
        2. Loop through form pages:
           a. Detect all visible form elements
           b. Fill each field using FormFiller
           c. Answer questions using QuestionAnswerer
           d. Upload resume if file input detected
           e. Click "Next" / "Review" / "Submit"
        3. Detect submission confirmation
        4. Take screenshot
        """
        ...

    async def _ensure_logged_in(self, page) -> bool:
        """Check if LinkedIn session is active. Return True if logged in."""
        ...

    async def _random_delay(self):
        """Sleep for random seconds between delay_min and delay_max"""
        ...

    async def _take_screenshot(self, page, job_id: str):
        """Save screenshot to output/screenshots/{job_id}_submitted.png"""
        ...
```

---

## File: `src/auto_applier/form_filler.py`

### Class: `FormFiller`

```python
class FormFiller:
    def __init__(self, answers: list[dict], profile: dict):
        self.answers = answers
        self.profile = profile

    async def fill_form_page(self, page) -> list[str]:
        """
        Detect and fill all form fields on the current Easy Apply page.
        Returns list of field labels that were filled.
        
        Field types to handle:
        - text input → fill with answer
        - number input → fill with answer
        - textarea → fill with answer
        - select/dropdown → select matching option
        - radio buttons → click matching option
        - checkbox → check if answer is truthy
        - file input → handled separately by applier (resume upload)
        """
        ...

    async def _detect_fields(self, page) -> list[dict]:
        """
        Find all form fields in the Easy Apply modal.
        Returns list of:
        {
            "element": Playwright locator,
            "type": "text" | "number" | "select" | "radio" | "checkbox" | "file" | "textarea",
            "label": "Question text or label text",
            "required": True/False
        }
        """
        ...

    async def _fill_field(self, page, field: dict, answer: str):
        """Fill a single field based on its type."""
        ...
```

---

## File: `src/auto_applier/question_answerer.py`

### Class: `QuestionAnswerer`

```python
class QuestionAnswerer:
    def __init__(self, llm_client: LLMClient, answers: list[dict], profile: dict):
        self.llm = llm_client
        self.answers = answers
        self.profile = profile
        self.log_path = "output/logs/new_questions.log"

    def get_answer(self, question_text: str, field_type: str, 
                   options: list[str] = None) -> str:
        """
        Two-tier answering:
        
        Tier 1 (Free, instant):
          Search answers.yaml for a matching pattern (case-insensitive substring).
          If found → return the pre-saved answer.
        
        Tier 2 (LLM, costs tokens):
          If no match in answers.yaml → send to LLM with profile context.
          Log the Q&A to new_questions.log for user to review later.
          Return the LLM-generated answer.
        """
        ...

    def _lookup_answer(self, question_text: str) -> str | None:
        """
        Iterate through answers.yaml entries.
        For each: if entry["pattern"].lower() is a substring of question_text.lower()
        → return entry["answer"]
        """
        ...

    def _ask_llm(self, question_text: str, field_type: str, 
                  options: list[str] = None) -> str:
        """Call LLM with question + profile context."""
        ...

    def _log_new_question(self, question: str, answer: str):
        """
        Append to output/logs/new_questions.log:
        [2026-09-02 14:30:00] Q: "How many years of React experience?"
        [2026-09-02 14:30:00] A: "4"
        ---
        """
        ...
```

### Question Answering — LLM Prompt

```
You are answering a job application form question. Be concise and direct.

Candidate Profile:
{profile_summary}

Question: "{question_text}"
Field type: {field_type}
{f"Available options: {options}" if options else ""}

Rules:
1. Answer ONLY from the candidate's actual profile. Do NOT fabricate.
2. Be concise. For number fields, return just the number. For text, 1-2 sentences max.
3. If the question asks about a skill the candidate doesn't have, answer honestly.
4. Return ONLY the answer text. No explanation, no quotes, no formatting.
```

---

## Browser Configuration

```python
# Playwright launch config
browser = await playwright.chromium.launch_persistent_context(
    user_data_dir="data/browser_profile",  # Persist cookies/session
    headless=False,                         # MUST be headed (anti-detection)
    viewport={"width": 1920, "height": 1080},
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
)
```

---

## LinkedIn Easy Apply — Key Selectors (may change — keep updated)

```python
# These are approximate — implement with resilient selectors (text-based preferred)
SELECTORS = {
    "easy_apply_button": 'button:has-text("Easy Apply")',
    "modal_container": '.jobs-easy-apply-modal',
    "next_button": 'button[aria-label="Continue to next step"]',
    "review_button": 'button[aria-label="Review your application"]',
    "submit_button": 'button[aria-label="Submit application"]',
    "dismiss_button": 'button[aria-label="Dismiss"]',
    "file_input": 'input[type="file"]',
    "form_fields": '.jobs-easy-apply-form-section__grouping',
    "success_message": 'h2:has-text("Your application was sent")',
}
```

> **Note to implementing agent:** LinkedIn updates their UI frequently. Use text-based selectors (`has-text`, `aria-label`) rather than CSS class selectors where possible. They're more resilient to UI changes.

---

## Error Handling

- "Easy Apply" button not found → job may require external application. Set `status = QUEUED_FOR_MANUAL`
- Modal doesn't open within 10s → skip, log error
- Unknown form field type → skip field, log warning
- Application already submitted (LinkedIn shows "Applied") → skip, set `status = APPLIED`
- Daily limit reached → stop processing, return partial results
- Browser crashes → catch exception, save state, close browser, report to user

---

## Test Scenarios (`tests/test_auto_applier.py`)

1. **Test answer lookup:** Question "years of experience" matches pattern from answers.yaml
2. **Test LLM fallback:** Question with no pattern match → triggers LLM call → answer logged to file
3. **Test daily limit:** If 25 jobs approved but limit is 20 → only 20 processed
4. **Test delay range:** Verify random delay is between min and max
5. **Test error recovery:** Simulate Easy Apply button missing → verify status becomes QUEUED_FOR_MANUAL
6. **Integration test:** Full E2E with mock Playwright page (if feasible)
