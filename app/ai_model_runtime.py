from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import DATA_DIR

RUNTIME_DIR = DATA_DIR / "ai"
LOCK_FILE = RUNTIME_DIR / "model-runtime.lock"
STATE_FILE = RUNTIME_DIR / "model-runtime-state.json"
OPERATOR_PENDING_FILE = RUNTIME_DIR / "model-operator.pending"
PENDING_MAX_AGE_SECONDS = 300


class ModelBusy(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_state(payload: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _operator_pending() -> bool:
    try:
        age = time.time() - OPERATOR_PENDING_FILE.stat().st_mtime
        if age > PENDING_MAX_AGE_SECONDS:
            OPERATOR_PENDING_FILE.unlink(missing_ok=True)
            return False
        return True
    except OSError:
        return False


def runtime_status() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            value = {}
    except Exception:
        value = {}
    value["operator_pending"] = _operator_pending()
    return value


@contextmanager
def model_slot(
    owner: str,
    *,
    priority: str = "background",
    wait_seconds: float = 2.0,
) -> Iterator[dict]:
    """Cross-process Ollama serialization with operator priority.

    Background workers fail fast when an operator request is waiting. This does
    not grant the model any execution capability; it only schedules model use.
    """
    owner = str(owner or "unknown")[:100]
    operator = priority == "operator"
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if operator:
        OPERATOR_PENDING_FILE.write_text(
            json.dumps({"owner": owner, "at": _now_iso(), "pid": os.getpid()}),
            encoding="utf-8",
        )

    handle = LOCK_FILE.open("a+", encoding="utf-8")
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    acquired = False
    try:
        while True:
            if not operator and _operator_pending():
                raise ModelBusy("operator_priority_waiting")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ModelBusy("ollama_model_slot_busy")
                time.sleep(0.1)

        if operator:
            OPERATOR_PENDING_FILE.unlink(missing_ok=True)
        started = time.monotonic()
        state = {
            "active": True,
            "owner": owner,
            "priority": priority,
            "pid": os.getpid(),
            "started_at": _now_iso(),
        }
        _write_state(state)
        yield state
        elapsed = int((time.monotonic() - started) * 1000)
        _write_state({
            "active": False,
            "last_owner": owner,
            "last_priority": priority,
            "last_duration_ms": elapsed,
            "released_at": _now_iso(),
        })
    finally:
        if operator:
            OPERATOR_PENDING_FILE.unlink(missing_ok=True)
        if acquired:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
