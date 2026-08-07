from app import service_watchdog


def _state(active: str, *, result: str = "success", sub: str | None = None) -> dict[str, str]:
    return {
        "LoadState": "loaded",
        "ActiveState": active,
        "SubState": sub or active,
        "Result": result,
        "UnitFileState": "enabled",
    }


def test_failed_oneshot_with_active_retry_timer_is_attention_not_critical():
    unit = "top40-archiver-auto-update.service"
    timer = "top40-archiver-auto-update.timer"
    states = {
        unit: _state("failed", result="exit-code"),
        timer: _state("active", sub="waiting"),
    }

    health, display, explanation = service_watchdog._logical_state(unit, states[unit], states)

    assert health == "attention"
    assert "retry" in display
    assert "timer" in explanation.lower()


def test_failed_oneshot_without_active_retry_timer_remains_critical():
    unit = "top40-archiver-auto-update.service"
    timer = "top40-archiver-auto-update.timer"
    states = {
        unit: _state("failed", result="exit-code"),
        timer: _state("inactive", sub="dead"),
    }

    health, display, explanation = service_watchdog._logical_state(unit, states[unit], states)

    assert health == "critical"
    assert "zonder actieve retry" in display
    assert "niet actief" in explanation


def test_inactive_oneshot_with_active_timer_is_normal_standby():
    unit = "top40-archiver-freshness.service"
    timer = "top40-archiver-freshness.timer"
    states = {
        unit: _state("inactive", result="success", sub="dead"),
        timer: _state("active", sub="waiting"),
    }

    health, display, _ = service_watchdog._logical_state(unit, states[unit], states)

    assert health == "healthy"
    assert display == "stand-by"
