from __future__ import annotations

import os
import time
from pathlib import Path

from app import safe_temp_cleanup


def _age(path: Path, hours: int = 48) -> None:
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


def test_cleanup_only_removes_old_partial_download_files(tmp_path, monkeypatch):
    root = tmp_path / "download-temp"
    root.mkdir()
    old_part = root / "unfinished.part"
    old_tmp = root / "worker.tmp"
    old_ytdl = root / "state.ytdl"
    completed_mp3 = root / "completed.mp3"
    completed_m4a = root / "completed.m4a"
    recent_part = root / "still-active.part"

    for path in (old_part, old_tmp, old_ytdl, completed_mp3, completed_m4a, recent_part):
        path.write_bytes(b"test")
    for path in (old_part, old_tmp, old_ytdl, completed_mp3, completed_m4a):
        _age(path)

    monkeypatch.setattr(safe_temp_cleanup, "TEMP_ROOT", root.resolve())
    result = safe_temp_cleanup.cleanup_stale_download_temp()

    assert result["ok"] is True
    assert result["removed_files"] == 3
    assert not old_part.exists()
    assert not old_tmp.exists()
    assert not old_ytdl.exists()
    assert completed_mp3.exists()
    assert completed_m4a.exists()
    assert recent_part.exists()
    assert result["policy"]["downloaded_audio_delete_allowed"] is False
