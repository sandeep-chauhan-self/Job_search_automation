import argparse
import asyncio
import logging
import webbrowser

import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Job Search Automation CLI")
    parser.add_argument(
        "command",
        choices=["discover", "dashboard", "prepare", "apply"],
        help="discover: scrape+score | dashboard: web control panel | prepare: build resumes | apply: submit",
    )
    parser.add_argument("--job-ids", default="", help="Comma-separated job IDs for prepare/apply")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind address (default: localhost only)")
    parser.add_argument("--port", type=int, default=8000, help="Dashboard port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab for the dashboard")

    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
