import argparse
import asyncio
import logging
import webbrowser

import uvicorn

from src.settings import configure_logging, settings

configure_logging(settings.log_level, settings.log_file)


def main():
    parser = argparse.ArgumentParser(description="Job Search Automation CLI")
    parser.add_argument(
        "command",
        choices=["discover", "dashboard", "prepare", "apply", "doctor"],
        help="discover: scrape+score | dashboard: web control panel | prepare: build resumes | "
             "apply: submit | doctor: check the setup",
    )
    parser.add_argument("--job-ids", default="", help="Comma-separated job IDs for prepare/apply")
    parser.add_argument("--host", default=settings.host, help="Dashboard bind address (default: localhost only)")
    parser.add_argument("--port", type=int, default=settings.port, help="Dashboard port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab for the dashboard")

    args = parser.parse_args()

    if args.command == "doctor":
        run_doctor()
        return

    if args.command == "dashboard":
        url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
        logging.info("Dashboard: %s", url)
        if args.host == "0.0.0.0":
            logging.warning("Binding 0.0.0.0 exposes the control panel to your network. Use 127.0.0.1 unless you mean it.")
        if not args.no_browser:
            webbrowser.open(url)
        uvicorn.run("src.dashboard.app:app", host=args.host, port=args.port, reload=False)
        return

    from src.orchestrator import Orchestrator

    orchestrator = Orchestrator()
    try:
        if args.command == "discover":
            orchestrator.run_pipeline()
            return

        job_ids = [j.strip() for j in args.job_ids.split(",") if j.strip()]
        if not job_ids:
            parser.error(f"--job-ids is required for the '{args.command}' command")

        if args.command == "prepare":
            asyncio.run(orchestrator.run_prepare(job_ids))
        else:
            asyncio.run(orchestrator.run_apply(job_ids))
    finally:
        orchestrator.close()


def run_doctor() -> None:
    """Check everything needed for a real run, so failures surface before a long scrape."""
    from src.assistant import ProfileAssistant
    from src.config_loader import load_profile, load_search_filters
    from src.database.connection import DB_PATH, get_db
    from src.database.models import Job

    print("Job Search Automation - setup check\n")
    ok = True

    print(f"  Database:      {DB_PATH}")
    db = get_db()
    try:
        print(f"  Jobs stored:   {db.query(Job).count()}")

        profile = load_profile()
        report = ProfileAssistant(db, None, profile).profile_completeness()
        print(f"  Profile:       {report['score']}% complete")
        if report["is_placeholder"]:
            ok = False
            print("     [FAIL] Still the sample 'John Doe' profile. Edit config/profile.yaml -")
            print("            every match score and generated resume depends on this being real.")
        elif report["missing"]:
            print(f"     [WARN] Missing sections: {', '.join(report['missing'])}")

        searches = load_search_filters().get("searches", [])
        print(f"  Searches:      {len(searches)} configured")
        if not searches:
            ok = False
            print("     [FAIL] No searches in config/search_filters.yaml - discovery will find nothing.")

        print(f"  LLM model:     {settings.llm_model}")
        if settings.is_llm_configured():
            print("  LLM key:       configured")
        else:
            ok = False
            print("     [FAIL] No LLM API key. Set JOBSEARCH_LLM_API_KEY or config/secrets.yaml.")

        print(f"  Apply mode:    {'DRY RUN (nothing submitted)' if settings.dry_run else 'LIVE'}")
        print(f"  Daily limit:   {settings.daily_limit}")

        try:
            import jobspy  # noqa: F401
            print("  Scraper:       python-jobspy installed")
        except ImportError:
            ok = False
            print("     [FAIL] python-jobspy missing. Run: pip install python-jobspy")

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                p.chromium.launch(headless=True).close()
            print("  Browser:       Playwright Chromium ready")
        except Exception as exc:
            ok = False
            print(f"     [FAIL] Playwright browser unavailable ({exc}).")
            print("            Run: playwright install chromium")
    finally:
        db.close()

    print("\n" + ("All checks passed." if ok else "Fix the [FAIL] items above before running."))


if __name__ == "__main__":
    main()
