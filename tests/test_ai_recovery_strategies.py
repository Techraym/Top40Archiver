from datetime import datetime, timedelta, timezone

from app import ai_recovery


def _item(**overrides):
    base = {
        "id": 1,
        "artist": "Vader Abraham & Mieke & De Kermisklanten",
        "title": "Het Leger Van Werkelozen",
        "category": "no_search_results",
        "error_message": "Geen YouTube-resultaten gevonden",
    }
    base.update(overrides)
    return base


def test_search_strategy_rotates_without_lowering_match_safety():
    item = _item()
    names = [ai_recovery._repair_strategy(item, n)[0] for n in range(4)]
    assert names == [
        "canonical_search",
        "simplified_artist",
        "title_first",
        "audio_fallback",
    ]


def test_compound_artist_is_simplified_for_second_strategy():
    strategy, query = ai_recovery._repair_strategy(_item(), 1)
    assert strategy == "simplified_artist"
    assert query == "Vader Abraham - Het Leger Van Werkelozen"


def test_transient_error_uses_backoff_not_query_relaxation():
    strategy, query = ai_recovery._repair_strategy(
        _item(category="rate_limit", error_message="HTTP Error 429"),
        4,
    )
    assert strategy == "backoff_retry"
    assert query is None


def test_recovery_counter_resets_when_error_changes():
    state = {
        "track_recoveries": {
            "1": {
                "count": 5,
                "fingerprint": "old",
                "category": "other",
                "last_at": datetime.now(timezone.utc).isoformat(),
            }
        }
    }
    record = ai_recovery._recovery_record(state, _item())
    assert record["count"] == 0
    assert record["category"] == "no_search_results"


def test_recovery_counter_resets_after_time_window():
    item = _item()
    fingerprint = ai_recovery._error_fingerprint(item["category"], item["error_message"])
    state = {
        "track_recoveries": {
            "1": {
                "count": 6,
                "fingerprint": fingerprint,
                "category": item["category"],
                "last_at": (
                    datetime.now(timezone.utc)
                    - timedelta(hours=ai_recovery.RECOVERY_RESET_HOURS + 1)
                ).isoformat(),
            }
        }
    }
    record = ai_recovery._recovery_record(state, item)
    assert record["count"] == 0
