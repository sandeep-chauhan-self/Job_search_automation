"""Background run execution with live log streaming for the dashboard.

Holds a single active run at a time. The dashboard polls `snapshot()` and
subscribes to `stream()` (Server-Sent Events) to watch progress in real time.
"""

import asyncio
import logging
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator

MAX_LOG_LINES = 500

PHASES = ["discovery", "scoring", "tailoring", "applying"]


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logs: deque[dict[str, Any]] = deque(maxlen=MAX_LOG_LINES)
        self._seq = 0
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._state: dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "active": False,
            "run_id": None,
            "kind": None,
            "phase": None,
            "status": "IDLE",
            "started_at": None,
            "finished_at": None,
            "progress": {"current": 0, "total": 0},
            "stats": {},
            "error": None,
        }

    # -- state ---------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["phases"] = PHASES
            state["log_seq"] = self._seq
            return state

    def logs_since(self, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [entry for entry in self._logs if entry["seq"] > after]

    def is_active(self) -> bool:
        with self._lock:
            return self._state["active"]

    # -- emitters used by the pipeline ---------------------------------------

    def log(self, message: str, level: str = "info") -> None:
        with self._lock:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "message": str(message),
            }
            self._logs.append(entry)
        logging.log(logging.ERROR if level == "error" else logging.INFO, message)

    def set_phase(self, phase: str, current: int = 0, total: int = 0) -> None:
        with self._lock:
            self._state["phase"] = phase
            self._state["progress"] = {"current": current, "total": total}

    def set_progress(self, current: int, total: int) -> None:
        with self._lock:
            self._state["progress"] = {"current": current, "total": total}

    def merge_stats(self, stats: dict[str, Any]) -> None:
        with self._lock:
            self._state["stats"].update(stats)

    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    # -- lifecycle -----------------------------------------------------------

    def request_cancel(self) -> bool:
        if not self.is_active():
            return False
        self._cancel.set()
        self.log("Cancellation requested - finishing current item then stopping.", "warn")
        return True

    def start(self, kind: str, target, *args) -> tuple[bool, str]:
        """Start `target(self, *args)` on a background thread. One run at a time."""
        with self._lock:
            if self._state["active"]:
                return False, "A run is already in progress."
            self._logs.clear()
            # Do NOT reset _seq here. A browser tab's SSE connection tracks its own
            # last-seen seq locally and never reconnects between runs; if seq reset
            # to 0, every entry in this new run would have seq <= that stale cursor
            # and would be filtered out of logs_since() forever for that connection.
            self._cancel.clear()
            self._state = self._idle_state()
            self._state.update(
                active=True,
                kind=kind,
                status="RUNNING",
                started_at=datetime.now(timezone.utc).isoformat(),
            )

        def worker() -> None:
            try:
                target(self, *args)
                final = "CANCELLED" if self._cancel.is_set() else "COMPLETED"
                self._finish(final)
            except Exception as exc:  # surfaced to the UI, never swallowed
                self.log(f"Run failed: {exc}", "error")
                logging.error("Run failed\n%s", traceback.format_exc())
                self._finish("FAILED", error=str(exc))

        self._thread = threading.Thread(target=worker, name=f"run-{kind}", daemon=True)
        self._thread.start()
        self.log(f"Started {kind} run.")
        return True, "started"

    def bind_run_id(self, run_id: str) -> None:
        with self._lock:
            self._state["run_id"] = run_id

    def _finish(self, status: str, error: str | None = None) -> None:
        with self._lock:
            self._state["active"] = False
            self._state["status"] = status
            self._state["phase"] = None
            self._state["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._state["error"] = error
        self.log(f"Run {status.lower()}.", "error" if status == "FAILED" else "info")

    # -- SSE -----------------------------------------------------------------

    async def stream(self) -> AsyncIterator[str]:
        """Yield SSE frames of new log lines plus periodic state snapshots."""
        last_seq = 0
        last_heartbeat = 0.0
        import json

        while True:
            for entry in self.logs_since(last_seq):
                last_seq = entry["seq"]
                yield f"event: log\ndata: {json.dumps(entry)}\n\n"

            now = time.monotonic()
            if now - last_heartbeat >= 1.0:
                last_heartbeat = now
                yield f"event: state\ndata: {json.dumps(self.snapshot())}\n\n"

            await asyncio.sleep(0.4)


run_manager = RunManager()
