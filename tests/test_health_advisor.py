from unittest.mock import patch

from app.health_advisor import build_health_advice


def healthy_snapshot():
    return {
        "score": 96,
        "status": "good",
        "diagnosis": "Alles gezond.",
        "disk_percent": 40.0,
        "disk_free_gb": 300.0,
        "worker_count": 1,
        "queue_failed": 0,
    }


@patch("app.health_advisor.health_events", return_value=[])
@patch("app.health_advisor.health_trends")
@patch("app.health_advisor.latest_health")
def test_stable_system_gets_safe_advice(latest, trends, events):
    latest.return_value = healthy_snapshot()
    trends.return_value = {"summary": {"score_direction": "stable", "diagnosis": "Stabiel."}}
    result = build_health_advice("24h")
    assert result["headline"]["key"] == "stable"
    assert result["headline"]["level"] == "info"


@patch("app.health_advisor.health_events", return_value=[])
@patch("app.health_advisor.health_trends")
@patch("app.health_advisor.latest_health")
def test_workers_are_flagged(latest, trends, events):
    snapshot = healthy_snapshot()
    snapshot["worker_count"] = 4
    latest.return_value = snapshot
    trends.return_value = {"summary": {"score_direction": "stable", "diagnosis": "Stabiel."}}
    result = build_health_advice("24h")
    assert any(item["key"] == "workers" for item in result["advice"])


@patch("app.health_advisor.health_events", return_value=[{"severity": "critical"}])
@patch("app.health_advisor.health_trends")
@patch("app.health_advisor.latest_health")
def test_critical_event_has_priority(latest, trends, events):
    latest.return_value = healthy_snapshot()
    trends.return_value = {"summary": {"score_direction": "stable", "diagnosis": "Stabiel."}}
    result = build_health_advice("24h")
    assert result["headline"]["level"] == "critical"
