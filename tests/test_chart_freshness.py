from datetime import datetime
from types import SimpleNamespace
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

    def fetch(chart_type, pair, *, prefer_current=False):
        calls.append((chart_type, pair, prefer_current))
        return {
            "ok": True,
            "chart_type": chart_type,
            "requested": f"{pair[0]}-W{pair[1]:02d}",
            "actual": f"{pair[0]}-W{pair[1]:02d}",
        }

    monkeypatch.setattr(chart_freshness, "_fetch_target_week", fetch)

    result = chart_freshness.run_freshness_check(force=True)
    assert result["ok"] is True
    assert calls == [
        ("top40", (2026, 32), True),
        ("tipparade", (2026, 32), True),
    ]
    assert result["after"]["expected_edition"] == "2026-W32"


def test_catchup_never_skips_over_failed_week(monkeypatch):
    calls = []

    def fetch(chart_type, pair, *, prefer_current=False):
        calls.append((pair, prefer_current))
        return {"ok": pair != (2026, 31), "chart_type": chart_type, "requested": f"{pair[0]}-W{pair[1]:02d}"}

    monkeypatch.setattr(chart_freshness, "_fetch_target_week", fetch)
    before = {"top40": "2026-W30", "tipparade": "2026-W30"}
    steps = chart_freshness._catch_up_chart("top40", before, (2026, 32))
    assert calls == [((2026, 31), False)]
    assert steps[-1]["ok"] is False


def test_latest_week_prefers_current_page_and_persists_only_exact_edition(monkeypatch):
    calls = []

    def fetch(target, chart_type):
        calls.append((target, chart_type))
        return SimpleNamespace(
            year=2026,
            week=32,
            edition_key="2026-W32",
            source_url="https://www.top40.nl/top40",
        )

    monkeypatch.setattr(chart_freshness, "fetch_chart_from_website", fetch)
    monkeypatch.setattr(chart_freshness, "_persist_chart", lambda chart, historical: {"new_track_ids": []})
    monkeypatch.setattr(chart_freshness, "process_queue", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no new tracks")))

    result = chart_freshness._fetch_target_week("top40", (2026, 32), prefer_current=True)

    assert result["ok"] is True
    assert result["source"] == "current"
    assert calls == [(None, "top40")]


def test_latest_week_falls_back_to_target_url_when_current_page_is_previous_week(monkeypatch):
    calls = []

    def fetch(target, chart_type):
        calls.append((target, chart_type))
        if target is None:
            return SimpleNamespace(
                year=2026,
                week=31,
                edition_key="2026-W31",
                source_url="https://www.top40.nl/top40",
            )
        return SimpleNamespace(
            year=2026,
            week=32,
            edition_key="2026-W32",
            source_url="https://www.top40.nl/top40/2026/week-32",
        )

    monkeypatch.setattr(chart_freshness, "fetch_chart_from_website", fetch)
    monkeypatch.setattr(chart_freshness, "_persist_chart", lambda chart, historical: {"new_track_ids": []})

    result = chart_freshness._fetch_target_week("top40", (2026, 32), prefer_current=True)

    assert result["ok"] is True
    assert result["source"] == "targeted_week"
    assert result["attempts"][0]["actual"] == "2026-W31"
    assert calls[0] == (None, "top40")
    assert calls[1][0].isocalendar().week == 32


def test_wrong_editions_are_never_persisted(monkeypatch):
    persisted = []

    def fetch(target, chart_type):
        return SimpleNamespace(
            year=2026,
            week=31,
            edition_key="2026-W31",
            source_url="https://www.top40.nl/top40",
        )

    monkeypatch.setattr(chart_freshness, "fetch_chart_from_website", fetch)
    monkeypatch.setattr(chart_freshness, "_persist_chart", lambda *args: persisted.append(args))

    result = chart_freshness._fetch_target_week("top40", (2026, 32), prefer_current=True)

    assert result["ok"] is False
    assert result["reason"] == "current_edition_not_available"
    assert persisted == []


def test_fresh_chart_performs_no_network_work(monkeypatch, tmp_path):
    current = {"ok": True, "expected_year": 2026, "expected_week": 32, "expected_edition": "2026-W32", "top40": "2026-W32", "tipparade": "2026-W32", "tipparade_enabled": True, "stale": []}
    monkeypatch.setattr(chart_freshness, "STATE_FILE", tmp_path / "freshness.json")
    monkeypatch.setattr(chart_freshness, "_state", lambda: current)
    monkeypatch.setattr(chart_freshness, "_fetch_target_week", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network should not run")))
    result = chart_freshness.run_freshness_check()
    assert result["ok"] is True
    assert result["action"] == "none"


def test_retry_window_is_ten_minutes():
    assert chart_freshness.RETRY_MINUTES == 10
