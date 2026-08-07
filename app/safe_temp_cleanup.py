from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import DATA_DIR

TEMP_ROOT = (DATA_DIR / "download-temp").resolve()
ALLOWED_SUFFIXES = {".part", ".tmp", ".ytdl"}
MIN_AGE_SECONDS = 24 * 60 * 60
MAX_BYTES_PER_RUN = 2 * 1024 * 1024 * 1024


def cleanup_stale_download_temp() -> dict:
    now = time.time()
    removed_files = 0
    removed_bytes = 0
    skipped = 0
    errors: list[str] = []

    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    for path in sorted(TEMP_ROOT.rglob("*")):
        if removed_bytes >= MAX_BYTES_PER_RUN:
            break
        try:
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if TEMP_ROOT not in resolved.parents:
                skipped += 1
                continue
            if path.suffix.casefold() not in ALLOWED_SUFFIXES:
                skipped += 1
                continue
            stat = path.stat()
            if now - stat.st_mtime < MIN_AGE_SECONDS:
                skipped += 1
                continue
            size = int(stat.st_size)
            # Alleen expliciet toegestane, oude gedeeltelijke downloadbestanden.
            path.unlink()
            removed_files += 1
            removed_bytes += size
        except OSError as exc:
            errors.append(f"{path}: {exc}"[-500:])

    payload = {
        "ok": not errors,
        "root": str(TEMP_ROOT),
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "removed_mb": round(removed_bytes / (1024 * 1024), 2),
        "skipped": skipped,
        "errors": errors[:20],
        "policy": {
            "downloaded_audio_delete_allowed": False,
            "allowed_suffixes": sorted(ALLOWED_SUFFIXES),
            "minimum_age_hours": 24,
            "maximum_bytes_per_run": MAX_BYTES_PER_RUN,
        },
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return payload


if __name__ == "__main__":
    raise SystemExit(0 if cleanup_stale_download_temp()["ok"] else 1)
