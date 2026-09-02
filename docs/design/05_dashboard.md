# Module 05: Semi-Auto Queue + Module 06: Dashboard

> **Depends on:** `00_shared_contracts.md`
> **Files to create:** `src/dashboard/__init__.py`, `src/dashboard/app.py`, `src/dashboard/routes.py`, `src/dashboard/static/index.html`, `src/dashboard/static/styles.css`, `src/dashboard/static/app.js`
> **External dependencies:** FastAPI, Uvicorn, Jinja2
> **LLM required:** No
> **Estimated effort:** Medium

> **Why combined:** The Semi-Auto Queue is just a filtered view in the dashboard. It doesn't need its own module — it's a database query + UI display.

---

## Purpose

Provide a local web dashboard (`localhost:8000`) where the user can:
1. **Monitor** all discovered/scored/applied jobs in a table view
2. **Review & Launch** auto-apply batches (approve/reject jobs before submission)
3. **Semi-Auto Queue** — see jobs needing manual application with download links for tailored resumes
4. **Track** application statuses through the pipeline
5. **Trigger** new pipeline runs
6. **View** analytics (apps/day, platform stats)

---

## Pages / Views

### 1. Pipeline Overview (`/`)
- Summary cards at top: Total Discovered | Scored | Applied | Interviews | Offers | Ghosted
- Full job table below with columns: Company, Title, Platform, Score, Status, Applied Date, Actions
- Filters: Status dropdown, Platform dropdown, Min Score slider, Date range
- Search bar (searches company + title)
- Sort by any column

### 2. Review & Launch (`/review`)
- Shows all jobs with `status = "REVIEW_QUEUED"` (LinkedIn Easy Apply only)
- Checkbox per job (all checked by default)
- Job details: Company, Title, Score %, Match Reasons
- "Preview Resume" link for each
- Big green **"Apply to Selected"** button at bottom
- User unchecks any jobs they don't want → clicks Apply → triggers Auto-Applier for checked jobs

### 3. Semi-Auto Queue (`/manual`)
- Shows all jobs with `status = "QUEUED_FOR_MANUAL"` (non-LinkedIn)
- For each job:
  - Company, Title, Platform, Score %
  - **"Open Job"** button → opens `job_url` in new tab
  - **"Download Resume"** button → downloads tailored resume PDF
  - **"Download Cover Letter"** button (if exists)
  - **"Mark Applied"** button → sets `status = "APPLIED"`, `applied_method = "manual"`

### 4. Analytics (`/analytics`)
- Applications per day (bar chart — last 30 days)
- Applications by platform (pie chart)
- Status breakdown (pie chart)
- Average match score of applied jobs
- Ghosting rate (% of APPLIED that became GHOSTED)
- New questions log viewer (shows `output/logs/new_questions.log` contents)

### 5. Settings (`/settings`)
- View/edit current config values (loaded from YAML)
- Start new run button
- View active run status

---

## File: `src/dashboard/app.py`

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .routes import router

app = FastAPI(title="Job Search Automation Dashboard")

# Serve frontend static files
app.mount("/static", StaticFiles(directory="src/dashboard/static"), name="static")

# API routes
app.include_router(router, prefix="/api")

# Root → serve index.html
@app.get("/")
async def root():
    return FileResponse("src/dashboard/static/index.html")
```

---

## File: `src/dashboard/routes.py`

### API Endpoints

```python
from fastapi import APIRouter, Query
router = APIRouter()

# ── Jobs ──────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(
    status: str = None,          # Filter by status
    platform: str = None,        # Filter by platform
    min_score: int = None,       # Filter by min match score
    search: str = None,          # Search company + title
    sort_by: str = "discovered_at",
    sort_order: str = "desc",    # "asc" or "desc"
    page: int = 1,
    page_size: int = 50
) -> dict:
    """
    Returns: {
        "jobs": [{ ...job fields... }],
        "total": 342,
        "page": 1,
        "page_size": 50
    }
    """
    ...

@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    """Return full job details including resume/cover letter paths."""
    ...

@router.patch("/jobs/{job_id}/status")
async def update_job_status(job_id: str, status: str, notes: str = None) -> dict:
    """
    Update job status. Used for:
    - Marking manual applications as APPLIED
    - Moving to INTERVIEW, OFFER, REJECTED, GHOSTED
    - Adding user notes
    """
    ...

# ── Review & Launch ───────────────────────────────────

@router.get("/review-queue")
async def get_review_queue() -> dict:
    """
    Returns LinkedIn jobs with status = "REVIEW_QUEUED".
    These are ready for auto-apply but awaiting user approval.
    """
    ...

@router.post("/review-queue/apply")
async def launch_auto_apply(job_ids: list[str]) -> dict:
    """
    Trigger the Auto-Applier for selected job IDs.
    Sets their status to "APPLYING" and starts the process.
    Returns: {"status": "started", "count": N}
    """
    ...

# ── Manual Queue ──────────────────────────────────────

@router.get("/manual-queue")
async def get_manual_queue() -> dict:
    """Returns non-LinkedIn jobs with status = "QUEUED_FOR_MANUAL"."""
    ...

# ── Files ─────────────────────────────────────────────

@router.get("/files/resume/{job_id}")
async def download_resume(job_id: str):
    """Serve the tailored resume PDF for download."""
    ...

@router.get("/files/cover-letter/{job_id}")
async def download_cover_letter(job_id: str):
    """Serve the cover letter PDF for download."""
    ...

# ── Pipeline Control ──────────────────────────────────

@router.post("/run/start")
async def start_run() -> dict:
    """
    Trigger a new pipeline run (discovery → scoring → resume generation).
    Runs in background thread.
    Returns: {"run_id": "...", "status": "started"}
    """
    ...

@router.get("/run/status")
async def get_run_status() -> dict:
    """
    Returns current/latest run status.
    {"run_id": "...", "status": "RUNNING", "jobs_discovered": 45, ...}
    """
    ...

# ── Analytics ─────────────────────────────────────────

@router.get("/analytics/summary")
async def get_analytics() -> dict:
    """
    Returns: {
        "total_applied": 150,
        "total_interviews": 12,
        "total_offers": 2,
        "total_ghosted": 85,
        "ghosting_rate": 0.57,
        "avg_match_score": 73,
        "apps_by_platform": {"linkedin": 80, "indeed": 40, ...},
        "apps_by_day": [{"date": "2026-09-01", "count": 15}, ...],
        "status_breakdown": {"APPLIED": 150, "INTERVIEW": 12, ...}
    }
    """
    ...

@router.get("/analytics/new-questions")
async def get_new_questions_log() -> dict:
    """Read and return contents of output/logs/new_questions.log"""
    ...

# ── Ghosting Cron ─────────────────────────────────────

@router.post("/cron/ghosting-check")
async def run_ghosting_check() -> dict:
    """
    UPDATE jobs SET status='GHOSTED' 
    WHERE status='APPLIED' 
    AND applied_at < date('now', '-{days_until_ghosted} days')
    
    Called daily. Can also be triggered manually.
    Returns: {"ghosted_count": N}
    """
    ...
```

---

## Frontend Design (`src/dashboard/static/`)

### `index.html`
- Single Page Application (SPA) feel — use `fetch()` to call API, update DOM
- Navigation tabs at top: **Overview | Review & Launch | Manual Apply | Analytics | Settings**
- No framework — vanilla JS with `fetch()` and DOM manipulation
- Responsive layout with CSS Grid

### `styles.css` — Design Tokens

```css
:root {
    /* Color palette — dark modern theme */
    --bg-primary: #0f1117;
    --bg-secondary: #1a1d26;
    --bg-card: #222530;
    --text-primary: #e4e6ed;
    --text-secondary: #8b8fa3;
    --accent: #6366f1;           /* Indigo */
    --accent-hover: #818cf8;
    --success: #22c55e;
    --warning: #f59e0b;
    --danger: #ef4444;
    --border: #2e3140;

    /* Typography */
    --font-family: 'Inter', -apple-system, sans-serif;
    --font-mono: 'JetBrains Mono', monospace;

    /* Spacing */
    --radius: 8px;
    --shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
}
```

### UI Components Needed

1. **Summary Cards** — rounded cards with icon + number + label (e.g., "📊 45 Scored")
2. **Data Table** — sortable, filterable, with status badges (colored pills)
3. **Status Badges** — color-coded pills: DISCOVERED=gray, SCORED=blue, APPLIED=green, INTERVIEW=purple, GHOSTED=red
4. **Action Buttons** — "Open Job" (external link icon), "Download Resume" (download icon), "Mark Applied" (check icon)
5. **Checkbox List** — for Review & Launch batch selection
6. **Simple Charts** — bar chart (apps/day) and pie chart (platform breakdown). Use `<canvas>` with Chart.js CDN or simple CSS-only bars
7. **Toast Notifications** — success/error feedback on actions
8. **Search + Filter Bar** — input + dropdowns above the table
9. **Run Status Indicator** — green dot = running, gray = idle, with progress text

---

## Ghosting Auto-Detection

Runs as a scheduled task. Two options for the implementing agent:

**Option A (Simple):** The dashboard backend runs the ghosting check SQL once when the dashboard starts, and again whenever the user visits the Analytics page.

**Option B (Proper):** Use `BackgroundTasks` in FastAPI or a simple `threading.Timer` to run the check every 24 hours while the dashboard is running.

Prefer Option A for simplicity.

---

## Error Handling

- Database not found → create it on first run (SQLAlchemy `create_all()`)
- Resume file missing for download → return 404 with helpful message
- Pipeline run already in progress → reject new run request with 409 Conflict
- API returns empty results → frontend shows "No jobs found. Start a new run." empty state

---

## Test Scenarios (`tests/test_dashboard.py`)

1. **Test GET /api/jobs** — returns paginated results with correct filters
2. **Test PATCH /api/jobs/{id}/status** — status updates correctly
3. **Test GET /api/review-queue** — returns only LinkedIn REVIEW_QUEUED jobs
4. **Test POST /api/review-queue/apply** — triggers applier for selected IDs
5. **Test GET /api/manual-queue** — returns only non-LinkedIn QUEUED_FOR_MANUAL jobs
6. **Test GET /api/analytics/summary** — returns correct aggregate counts
7. **Test ghosting check** — jobs older than 14 days get GHOSTED status
8. **Test file download** — resume PDF is served correctly
