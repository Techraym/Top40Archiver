from app import service_history
from app.history_rules import get_blacklisted_history_rule


def test_known_missing_top40_page_is_in_permanent_blacklist():
    rule = get_blacklisted_history_rule("top40", 1970, 53)

    assert rule is not None
    assert rule["source_url"] == "https://www.top40.nl/top40/1970/week-53"
    assert (rule["next_year"], rule["next_week"]) == (1971, 1)


def test_history_worker_skips_blacklisted_page_without_http(monkeypatch):
    updates: list[dict] = []

    def fail_if_requested(*_args, **_kwargs):
        raise AssertionError("De geblackliste URL mag niet via HTTP worden opgevraagd")

    monkeypatch.setattr(service_history, "fetch_chart_from_website", fail_if_requested)
    monkeypatch.setattr(service_history, "set_settings", lambda values: updates.append(values))

    settings = {
        "history_status": "running",
        "history_next_year": "1970",
        "history_next_week": "53",
    }
    result = service_history._run_chart_history(
        "top40",
        settings,
        current_pair=(1971, 2),
        batch=1,
        delay=0,
    )

    assert result["skipped"] == ["1970-W53"]
    assert result["next"] == "1971-W01"
    assert updates[-1]["history_next_year"] == 1971
    assert updates[-1]["history_next_week"] == 1
    assert updates[-1]["history_last_error"] == ""
    assert updates[-1]["history_enabled"] == "1"
