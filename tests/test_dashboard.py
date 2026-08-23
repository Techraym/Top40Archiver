from app.dashboard import download_chart, history_progress, percent, queue_summary


def test_percent():
    assert percent(25, 100) == 25.0
    assert percent(1, 0) == 0.0


def test_download_chart():
    chart = download_chart({"downloaded": 5, "pending": 3, "downloading": 1, "failed": 1})
    assert chart["total"] == 10
    assert chart["downloaded_percent"] == 50.0
    assert "conic-gradient" in chart["gradient"]


def test_queue_summary_uses_active_download_jobs():
    summary = queue_summary(
        {"pending": 8065, "downloading": 0},
        4,
    )
    assert summary == {
        "total": 8065,
        "waiting": 8061,
        "active": 4,
    }


def test_completed_history_becomes_current():
    progress = history_progress(
        {
            "history_start_year": "1965",
            "history_start_week": "1",
            "history_next_year": "2026",
            "history_next_week": "31",
            "history_status": "completed",
            "history_last_edition": "2026-W31",
            "last_edition": "2026-W31",
            "tip_history_start_year": "1967",
            "tip_history_start_week": "28",
            "tip_history_next_year": "2026",
            "tip_history_next_week": "31",
            "tip_history_status": "completed",
            "tip_history_last_edition": "2026-W31",
            "last_tipparade_edition": "2026-W31",
            "weekly_day": "Fri",
            "weekly_time": "15:00",
            "history_completed_at": "2026-08-03T22:00:00+02:00",
        }
    )
    assert progress["is_current"] is True
    assert progress["percent"] == 100.0
    assert progress["remaining"] == 0
    assert progress["title"] == "Archief is actueel"
    assert progress["next_label"] == "Fri 15:00"
    assert progress["top40"]["percent"] == 100.0
    assert progress["tipparade"]["percent"] == 100.0
