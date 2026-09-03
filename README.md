# Job Search Automation

A local-first pipeline that discovers job postings, scores them against your profile with an LLM, tailors a resume/cover letter per job, and (optionally) auto-applies on LinkedIn — with a human-in-the-loop review dashboard at every stage.

> Status: active development. See [TODO.md](TODO.md) and [CHANGELOG.md](CHANGELOG.md).

## How it works

```
Discover -> Score -> Review (dashboard) -> Tailor resume/cover letter -> Auto-apply -> Track
```

1. **Discovery** — scrapes LinkedIn, Indeed, Glassdoor, Naukri, and Google Jobs via [`python-jobspy`](https://pypi.org/project/python-jobspy/) using the filters in `config/search_filters.yaml`, dedupes results, and stores them in SQLite with status `DISCOVERED`.
2. **Scoring** — sends each job description plus your `config/profile.yaml` to an LLM (via LiteLLM) to produce a 0-100 match score, match reasons/gaps, and a `SCORED`/`SKIPPED` status.
3. **Human review** — you shortlist or skip scored jobs in the dashboard. Nothing proceeds without this step.
4. **Resume factory** — tailors your resume and cover letter per shortlisted job and renders them to PDF, moving the job to `RESUME_READY`. Every document is versioned, so regenerating never loses the previous copy.
5. **Auto-applier** — drives a visible Playwright browser through LinkedIn Easy Apply, filling fields and answering questions (pre-saved answers first, LLM fallback second). Defaults to dry-run.
6. **Tracking** — after applying, you track screening, interview rounds, offers, and rejections. Every status change, note, document, and contact is recorded on an append-only timeline per job.

Full module-by-module design docs live in [docs/design/](docs/design/00_shared_contracts.md).

## What it keeps track of

This is a corpus, not just a scraper. Per job it stores:

- **Timeline** — an append-only history of every status change, note, generated document, contact, and interview
- **Documents** — every resume and cover letter version ever generated, with the content snapshot and model used
- **Interviews** — rounds, dates, interviewers, mode, prep notes, feedback, outcomes
- **Contacts** — recruiters, hiring managers, referrals, with their details
- **Reminders** — follow-up dates and posting deadlines that surface in the Today view
- **Your labels** — favourites, priority, free-form tags, referral name, rejection reason

## Project structure

```
config/          System settings, secrets, profile, search filters, saved answers
src/
  discovery/      Job scraping (JobSpy)
  scoring/        LLM-based match scoring
  resume_factory/ Resume/cover letter tailoring + HTML->PDF rendering
  auto_applier/   Playwright-driven LinkedIn Easy Apply automation
  dashboard/      FastAPI dashboard + background run manager
  llm/            LiteLLM client wrapper + cost tracking
  database/       SQLAlchemy models + connection
  orchestrator.py Pipeline coordinator used by main.py
templates/        Resume/cover letter HTML + CSS templates
data/             SQLite database (gitignored)
output/           Generated resumes, cover letters, screenshots, logs (gitignored)
tests/            Pytest suite for each module
aihawk_core/      Vendored AIHawk (Jobs_Applier_AI_Agent_AIHawk) reference implementation
godsscion/        Reference/automation runner assets
```

## Requirements

- Python 3.11+
- An LLM provider key (OpenAI, DeepSeek, Ollama, etc. via LiteLLM)
- Playwright browsers (`playwright install`) for auto-apply

## Setup

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install
```

Copy `config/secrets.example.yaml` to `config/secrets.yaml` and `config/profile.example.yaml` to `config/profile.yaml`, then fill in your real values. Every `secrets.yaml` is gitignored — never commit real credentials.

**Your profile is the single most important input.** Match scores compare it against each job description, tailored resumes are built only from facts listed in it, and the assistant refuses to answer anything not written there. The dashboard shows a warning banner until it is filled in.

| File | Purpose |
|------|---------|
| `config/config.yaml` | LLM provider, daily apply limit, score threshold, delays, dry-run toggle |
| `config/secrets.yaml` | LLM API key, LinkedIn credentials (gitignored) |
| `config/profile.yaml` | Your resume data: experience, skills, education, preferences |
| `config/search_filters.yaml` | Job titles, locations, work mode, include/exclude keywords |
| `config/answers.yaml` | Pre-saved answers for common application questions |

## Usage

Everything is drivable from the dashboard — start there:

```powershell
python main.py doctor      # check your setup first
python main.py dashboard
```

`doctor` verifies your profile, searches, LLM key, scraper, and browser before you waste time on a long run. The dashboard opens `http://localhost:8000` and binds to localhost only. Use `--port 8777` if 8000 is taken, and `--host 0.0.0.0` only if you deliberately want LAN access.

### Dashboard views

| View | What it is for |
|------|----------------|
| **Today** | The only view you need most days: interviews coming up, follow-ups due, postings closing soon, jobs ready to apply, and applications that have gone quiet |
| **All Jobs** | Your full corpus. Filter by status, platform, score, or text; star favourites; bulk shortlist |
| **Review & Launch** | Shortlisted jobs waiting for a tailored resume or submission |
| **Applications** | A board of everything you applied to, by stage: applied, screening, interview, offer, rejected, ghosted |
| **Interviews** | Every round with dates, interviewers, and outcomes you can update inline |
| **Documents** | Every resume and cover letter ever generated, versioned per job and downloadable |
| **Ask About Me** | Grounded Q&A over your profile and job history |
| **Analytics** | Conversion funnel, response rate, interview rate, platform mix, LLM spend |

Opening any job gives you a detail drawer with its full **timeline** — every status change, note, document, contact, and interview, in order — plus controls for priority, follow-up reminders, deadlines, notes, contacts, and interview rounds.

**Export** downloads your whole corpus as CSV so your job search data is never trapped in this app.

### Headless commands

```powershell
python main.py discover                      # scrape + score
python main.py prepare --job-ids <id1>,<id2> # tailor + render PDFs
python main.py apply   --job-ids <id1>,<id2> # submit
```

## Ask About Me

The assistant answers questions like *"which applications have gone quiet?"* or *"summarise my experience for a recruiter"* using **only** your `profile.yaml` and job data.

It is built to refuse rather than guess:

- the model only ever sees facts assembled from your profile and database
- it is instructed to reply *"That is not in your profile or job data"* when something is missing, and never to infer skills you did not list
- every answer cites the source tags it used, so you can verify any claim

This matters because these answers can end up in real applications. A plausible-sounding invented detail is worse than no answer.

## Apply safety

`application.dry_run` in `config/config.yaml` defaults to **true**. In dry-run mode the browser opens each posting, fills the Easy Apply form, screenshots the final review step to `output/screenshots/`, and stops without submitting. Review those screenshots before setting `dry_run: false`.

Other guardrails:

- `daily_limit` is enforced against a rolling 24-hour window of real applications
- delays between actions are randomized between `delay_min_seconds` and `delay_max_seconds`
- jobs that are not LinkedIn Easy Apply, or that have no tailored resume on disk, are routed to the Manual Queue instead of being marked applied
- `headless: false` keeps the browser visible so you can watch and intervene

## Production configuration

Environment variables override `config.yaml`, so the same checkout runs in different modes without editing tracked files:

| Variable | Purpose |
|----------|---------|
| `JOBSEARCH_LLM_API_KEY` | LLM key — preferred over `secrets.yaml` so keys never touch a file |
| `JOBSEARCH_LLM_MODEL` | LiteLLM model string |
| `JOBSEARCH_DRY_RUN` | `false` to submit applications for real |
| `JOBSEARCH_HOST` / `JOBSEARCH_PORT` | Dashboard bind address |
| `JOBSEARCH_DB_PATH` | Move the database elsewhere |
| `JOBSEARCH_LOG_FILE` | Also write logs to a file |
| `JOBSEARCH_DAILY_LIMIT` | Max applications per rolling 24h |
| `JOBSEARCH_STALE_DAYS` | Days before an application is flagged as gone quiet |

The database schema self-upgrades on startup: new tables are created and new columns are added to existing tables, so upgrading never requires a manual migration or a wipe.

## Testing

```powershell
pytest
```

Tests run against isolated temporary databases and never touch `data/jobs.db`.

## Security notes

- Never commit real values in any `secrets.yaml`. If a key was ever committed, rotate it — removing it from the working tree does not remove it from git history.
- The dashboard has no authentication. It binds to localhost by default; do not expose it to a network.
- Document downloads are confined to the `output/` directory.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — high-level system design
- [docs/design/](docs/design/00_shared_contracts.md) — per-module implementation specs (shared contracts, discovery, scoring, resume factory, auto-applier, dashboard, LLM layer, orchestrator)
- [docs/API.md](docs/API.md), [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) — API and schema reference
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) — contribution and security policy

## License

See [LICENSE.md](LICENSE.md).

