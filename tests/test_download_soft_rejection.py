from app.download_manager import _should_persist_rejection


def test_try_other_provider_is_not_permanent_rejection():
    assert _should_persist_rejection("try_other_provider") is False


def test_low_match_remains_permanent_rejection():
    assert _should_persist_rejection("low_match") is True


def test_invalid_candidate_reason_remains_permanent_rejection():
    assert _should_persist_rejection("wrong_duration") is True
