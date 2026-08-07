from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR

BACKUP_ROOT = DATA_DIR / "backups" / "version-rollback"


def _parse_metadata(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def backup_health() -> dict[str, Any]:
    candidates = []
    try:
        candidates = sorted(
            [p for p in BACKUP_ROOT.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        pass

    latest = candidates[0] if candidates else None
    if latest is None:
        return {
            "ok": False,
            "available": False,
            "root": str(BACKUP_ROOT),
            "reason": "Nog geen geverifieerde versie-rollbackup gevonden.",
        }

    marker = latest / "BACKUP_OK"
    manifest = latest / "manifest.sha256"
    metadata = _parse_metadata(latest / "metadata.json")
    created = metadata.get("created_at")
    age_hours = None
    if created:
        try:
            parsed = datetime.fromisoformat(str(created))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_hours = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0)
        except ValueError:
            pass

    required = [
        latest / "app.tar.gz",
        latest / "VERSION",
        latest / "git-sha",
        latest / "metadata.json",
        manifest,
        marker,
    ]
    missing = [str(p.name) for p in required if not p.exists()]
    ok = not missing and marker.exists() and manifest.exists()
    return {
        "ok": ok,
        "available": True,
        "root": str(BACKUP_ROOT),
        "latest": str(latest),
        "version": metadata.get("version"),
        "git_sha": metadata.get("git_sha"),
        "created_at": created,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "verified_marker": marker.exists(),
        "manifest_present": manifest.exists(),
        "database_backup": (latest / "top40.sqlite3").exists(),
        "ai_memory_backup": (latest / "ai_memory.sqlite").exists(),
        "repository_bundle": (latest / "repository.bundle").exists(),
        "missing": missing,
        "audio_library_touched": bool(metadata.get("audio_library_touched", False)),
    }
