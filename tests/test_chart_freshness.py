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


def test_missing_pairs_are_sequential_and_cross_year_boundary():
    assert chart_freshness.missing_pairs((2026, 30), (2026, 32)) == [(2026, 31), (2026, 32)]
    assert chart_freshness.missing_pairs((2025, 52), (2026, 2)) == [(2026, 1), (2026, 2)]
    assert chart_freshness.missing_pairs(None, (2026, 32)) == [(2026, 32)]


def test_stale_charts_catch_up_targeted_weeks(monkeypatch, tmp_path):
    states = [
        {"ok": False, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W31", "tipparade": "2026-W31", "tipparade_enabled": True, "stale": ["top40", "tipparade"]},
        {"ok": True, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W32", "tipparade": "2026-W32", "tipparade_enabled": True, "stale": []},
    ]
    monkeypatch.setattr(chart_freshness, "STATE_FILE", tmp_path / "freshness.json")
    monkeypatch.setattr(chart_freshness, "_state", lambda: states.pop(0))
    monkeypatch.setattr(chart_freshness, "_recent_attempt", lambda now: False)
    calls = []
    monkeypatch.setattr(
        chart_freshness,
        "_fetch_target_week",
        lambda chart_type, pair: calls.append((chart_type, pair)) or {
            "ok": True,
            "chart_type": chart_type,
            "requested": f"{pair[0]}-W{pair[1]:02d}",
            "actual": f"{pair[0]}-W{pair[1]:02d}",
        },
    )

    result = chart_freshness.run_freshness_check(force=True)
    assert result["ok"] is True
    assert calls == [("top40", (2026, 32)), ("tipparade", (2026, 32))]
    assert result["after"]["expected_edition"] == "2026-W32"


def test_catchup_never_skips_over_failed_week(monkeypatch):
    calls = []

    def fetch(chart_type, pair):
        calls.append(pair)
        return {"ok": pair != (2026, 31), "chart_type": chart_type, "requested": f"{pair[0]}-W{pair[1]:02d}"}

    monkeypatch.setattr(chart_freshness, "_fetch_target_week", fetch)
    before = {"top40": "2026-W30", "tipparade": "2026-W30"}
    steps = chart_freshness._catch_up_chart("top40", before, (2026, 32))
    assert calls == [(2026, 31)]
    assert steps[-1]["ok"] is False


def test_fresh_chart_performs_no_network_work(monkeypatch, tmp_path):
    current = {"ok": True, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W32", "tipparade": "2026-W32", "tipparade_enabled": True, "stale": []}
    monkeypatch.setattr(chart_freshness, "STATE_FILE", tmp_path / "freshness.json")
    monkeypatch.setattr(chart_freshness, "_state", lambda: current)
    monkeypatch.setattr(chart_freshness, "_fetch_target_week", lambda *args: (_ for _ in ()).throw(AssertionError("network should not run")))
    result = chart_freshness.run_freshness_check()
    assert result["ok"] is True
    assert result["action"] == "none"
