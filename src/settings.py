"""Runtime settings.

Environment variables win over config.yaml so the same checkout can run in
different modes without editing tracked files. Secrets should come from the
environment in production rather than config/secrets.yaml.
"""

import logging
import os
import sys

from src.config_loader import load_config, load_secrets

TRUE_VALUES = {"1", "true", "yes", "on"}

# Anchor every path to the repo, not the working directory. Relative paths would
# write documents to one place and look for them in another whenever the app is
# launched from a different folder (a service, a scheduler, an IDE).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.environ.get("JOBSEARCH_OUTPUT_DIR") or os.path.join(PROJECT_ROOT, "output")
TEMPLATE_DIR = os.environ.get("JOBSEARCH_TEMPLATE_DIR") or os.path.join(PROJECT_ROOT, "templates")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.warning("%s=%r is not an integer; using %s", name, raw, default)
        return default


class Settings:
    def __init__(self) -> None:
        config = load_config()
        secrets = load_secrets()
        app = config.get("application", {})
        llm = config.get("llm", {})

        self.host = os.environ.get("JOBSEARCH_HOST", "127.0.0.1")
        self.port = _env_int("JOBSEARCH_PORT", 8000)
        self.log_level = os.environ.get("JOBSEARCH_LOG_LEVEL", "INFO").upper()
        self.log_file = os.environ.get("JOBSEARCH_LOG_FILE")

        # Env var first so a real key never has to be written to a tracked file.
        self.llm_api_key = os.environ.get("JOBSEARCH_LLM_API_KEY") or secrets.get("llm_api_key")
        self.llm_model = os.environ.get("JOBSEARCH_LLM_MODEL") or llm.get("provider", "gpt-4o-mini")

        self.dry_run = _env_bool("JOBSEARCH_DRY_RUN", app.get("dry_run", True))
        self.headless = _env_bool("JOBSEARCH_HEADLESS", app.get("headless", False))
        self.daily_limit = _env_int("JOBSEARCH_DAILY_LIMIT", app.get("daily_limit", 25))

        self.stale_after_days = _env_int("JOBSEARCH_STALE_DAYS", 10)

    def is_llm_configured(self) -> bool:
        return bool(self.llm_api_key) and self.llm_api_key != "your-api-key-here"

    def as_dict(self) -> dict:
        """Safe for the UI - never expose the key itself."""
        return {
            "host": self.host,
            "port": self.port,
            "llm_model": self.llm_model,
            "llm_configured": self.is_llm_configured(),
            "dry_run": self.dry_run,
            "headless": self.headless,
            "daily_limit": self.daily_limit,
            "stale_after_days": self.stale_after_days,
        }


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=handlers,
        force=True,
    )

    # litellm logs one INFO line per request, which drowns out pipeline progress.
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


settings = Settings()
