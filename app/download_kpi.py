from __future__ import annotations

from typing import Any

from .db import connect
from .download_db import init_download_db


def youtube_dependency_kpis() -> dict[str, Any]:
    init_download_db()
    with connect() as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN provider='youtube' THEN 1 ELSE 0 END) AS youtube,
                   SUM(CASE WHEN provider='youtube_music' THEN 1 ELSE 0 END) AS youtube_music
            FROM download_provider_attempts
            WHERE success=1 AND datetime(completed_at)>=datetime('now','-1 day')
            """
        ).fetchone()
    total = int(row["total"] or 0)
    youtube = int(row["youtube"] or 0)
    youtube_music = int(row["youtube_music"] or 0)
    non_youtube = max(0, total - youtube - youtube_music)
    direct_dependency = round(youtube / total * 100, 1) if total else 0.0
    family_dependency = round((youtube + youtube_music) / total * 100, 1) if total else 0.0
    return {
        "downloads_24h": total,
        "without_youtube_24h": non_youtube,
        "youtube_music_24h": youtube_music,
        "youtube_24h": youtube,
        "youtube_dependency_percent": direct_dependency,
        "youtube_family_dependency_percent": family_dependency,
        "youtube_dependency_target_percent": 10.0,
        "youtube_dependency_target_met": direct_dependency < 10.0 if total else None,
    }
