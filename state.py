"""State persistence: tracks whether we've already alerted."""
import json
from datetime import datetime, timezone
from pathlib import Path

from config import STATE_FILE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    p = Path(STATE_FILE)
    if not p.exists():
        return {
            "alerted": False,
            "alerted_at": None,
            "checks": 0,
            "last_check": None,
            "last_status": None,
            "last_method": None,
            "last_error": None,
        }
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"alerted": False, "checks": 0}


def save(state: dict) -> None:
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))


def record_check(state: dict, status: str, method: str, error: str | None = None) -> None:
    state["checks"] = state.get("checks", 0) + 1
    state["last_check"] = _now()
    state["last_status"] = status
    state["last_method"] = method
    state["last_error"] = error


def mark_alerted(state: dict) -> None:
    state["alerted"] = True
    state["alerted_at"] = _now()
