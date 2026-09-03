# Job Search Automation

A local-first pipeline that discovers job postings, scores them against your profile with an LLM, tailors a resume/cover letter per job, and (optionally) auto-applies on LinkedIn — with a human-in-the-loop review dashboard at every stage.

> Status: active development. See [TODO.md](TODO.md) and [CHANGELOG.md](CHANGELOG.md).

## How it works

```
Discover -> Score -> Review (dashboard) -> Tailor resume/cover letter -> Auto-apply -> Track
```

1. **Discovery** — scrapes LinkedIn, Indeed, Glassdoor, Naukri, and Google Jobs via [`python-jobspy`](https://pypi.org/project/python-jobspy/) using the filters in `config/search_filters.yaml`, dedupes results, and stores them in SQLite with status `DISCOVERED`.
2. **Scoring** — sends each job description plus your `config/profile.yaml` to an LLM (via LiteLLM) to produce a 0-100 match score, match reasons/gaps, and a `SCORED`/`SKIPPED` status.
3. **Human review** — you approve or reject scored jobs in the dashboard. Nothing proceeds without this step.
4. **Resume factory** — tailors your resume and cover letter per approved job and renders them to PDF, moving the job to `RESUME_READY`.
5. **Auto-applier** — drives a visible Playwright browser through LinkedIn Easy Apply, filling fields and answering questions (pre-saved answers first, LLM fallback second). Defaults to dry-run.
6. **Dashboard** — a FastAPI control panel at `localhost:8000` to trigger every stage, watch live logs, review jobs, and track outcomes.

Full module-by-module design docs live in [docs/design/](docs/design/00_shared_contracts.md).

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

Copy `config/secrets.example.yaml` to `config/secrets.yaml` and fill in your real values. Every `secrets.yaml` is gitignored — never commit real credentials.

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
python main.py dashboard
```

It opens `http://localhost:8000` and binds to localhost only. Use `--port 8777` if 8000 is taken, and `--host 0.0.0.0` only if you deliberately want LAN access.

From the dashboard you can:

- **Run Discovery** — scrape and score in the background, watching every step stream into the Live Activity panel
- **Filter and search** the jobs table by status, platform, minimum score, or free text
- **Click any row** for the full description, match reasons, gaps, LLM cost, and status controls
- **Select jobs** to bulk approve/reject, generate tailored resumes, or apply
- **Stop Run** to cancel cleanly after the current item
- **Analytics** for the conversion funnel, platform mix, and LLM spend
- **Run History** for every past pipeline execution

The same steps are available headlessly:

```powershell
python main.py discover                      # scrape + score
python main.py prepare --job-ids <id1>,<id2> # tailor + render PDFs
python main.py apply   --job-ids <id1>,<id2> # submit
```

## Apply safety

`application.dry_run` in `config/config.yaml` defaults to **true**. In dry-run mode the browser opens each posting, fills the Easy Apply form, screenshots the final review step to `output/screenshots/`, and stops without submitting. Review those screenshots before setting `dry_run: false`.

Other guardrails:

- `daily_limit` is enforced against a rolling 24-hour window of real applications
- delays between actions are randomized between `delay_min_seconds` and `delay_max_seconds`
- jobs that are not LinkedIn Easy Apply, or that have no tailored resume on disk, are routed to the Manual Queue instead of being marked applied
- `headless: false` keeps the browser visible so you can watch and intervene

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

