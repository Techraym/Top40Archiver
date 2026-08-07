from datetime import datetime
from zoneinfo import ZoneInfo

from app import chart_freshness

TZ = ZoneInfo("Europe/Amsterdam")


def test_friday_afternoon_requires_current_iso_week():
    now = datetime(2026, 8, 7, 15, 30, tzinfo=TZ)
    assert now.isocalendar().week == 32
    assert chart_freshness.expected_latest_pair(now) == (2026, 32)


def test_friday_morning_does_not_mark_new_week_stale_before_publish_window():
    now = datetime(2026, 8, 7, 10, 0, tzinfo=TZ)
    assert chart_freshness.expected_latest_pair(now) == (2026, 31)


def test_stale_chart_runs_normal_import_then_website_fallback(monkeypatch, tmp_path):
    states = [
        {"ok": False, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W31", "tipparade": "2026-W31", "tipparade_enabled": True, "stale": ["top40", "tipparade"]},
        {"ok": False, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W31", "tipparade": "2026-W31", "tipparade_enabled": True, "stale": ["top40", "tipparade"]},
        {"ok": True, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W32", "tipparade": "2026-W32", "tipparade_enabled": True, "stale": []},
    ]
    monkeypatch.setattr(chart_freshness, "STATE_FILE", tmp_path / "freshness.json")
    monkeypatch.setattr(chart_freshness, "_state", lambda: states.pop(0))
    monkeypatch.setattr(chart_freshness, "_recent_attempt", lambda now: False)
    normal_calls = []
    monkeypatch.setattr(chart_freshness, "import_latest", lambda force=False: normal_calls.append(force) or {"results": {}})
    fallback_calls = []
    monkeypatch.setattr(
        chart_freshness,
        "_website_fallback",
        lambda chart_type, expected: fallback_calls.append((chart_type, expected)) or {"ok": True, "chart_type": chart_type, "actual": "2026-W32"},
    )

    result = chart_freshness.run_freshness_check(force=True)
    assert result["ok"] is True
    assert normal_calls == [False]
    assert fallback_calls == [("top40", (2026, 32)), ("tipparade", (2026, 32))]
    assert result["after"]["expected_edition"] == "2026-W32"


def test_fresh_chart_performs_no_network_work(monkeypatch, tmp_path):
    current = {"ok": True, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W32", "tipparade": "2026-W32", "tipparade_enabled": True, "stale": []}
    monkeypatch.setattr(chart_freshness, "STATE_FILE", tmp_path / "freshness.json")
    monkeypatch.setattr(chart_freshness, "_state", lambda: current)
    monkeypatch.setattr(chart_freshness, "import_latest", lambda force=False: (_ for _ in ()).throw(AssertionError("network should not run")))
    result = chart_freshness.run_freshness_check()
    assert result["ok"] is True
    assert result["action"] == "none"
