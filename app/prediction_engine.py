from __future__ import annotations

from typing import Any

from .health_engine import latest_health
from .health_trends import health_trends


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


def build_predictions(range_key: str = '24h') -> dict[str, Any]:
    health = latest_health()
    trend = health_trends(range_key)
    summary = trend.get('summary') or {}
    workers = int(health.get('worker_count') or 1)
    failed = int(health.get('queue_failed') or 0)
    pending = int(health.get('queue_pending') or 0)
    disk = float(health.get('disk_percent') or 0)
    cpu = float(health.get('cpu_percent') or 0)
    memory = float(health.get('memory_percent') or 0)
    db_ms = float(health.get('database_latency_ms') or 0)
    failed_change = int(summary.get('failed_change') or 0)
    direction = str(summary.get('score_direction') or 'stable')

    youtube_risk = _clamp(8 + max(0, workers - 1) * 24 + failed * 1.4 + max(0, failed_change) * 5)
    storage_risk = _clamp(max(0, disk - 70) * 3.2)
    database_risk = _clamp(max(0, db_ms - 50) / 4 + max(0, memory - 75) * 1.5)
    system_risk = _clamp(max(0, cpu - 65) * 1.2 + max(0, memory - 75) * 1.3 + (15 if direction == 'down' else 0))
    throughput_per_hour = 18.0 if workers == 1 else max(6.0, 18.0 / workers)
    if failed_change > 0: throughput_per_hour *= 0.65
    queue_hours = round(pending / throughput_per_hour, 1) if pending else 0.0
    risks = [
        {'key': 'youtube', 'label': 'YouTube-beperking', 'risk': youtube_risk},
        {'key': 'storage', 'label': 'Opslagprobleem', 'risk': storage_risk},
        {'key': 'database', 'label': 'Databasevertraging', 'risk': database_risk},
        {'key': 'system', 'label': 'Systeembelasting', 'risk': system_risk},
    ]
    risks.sort(key=lambda item: item['risk'], reverse=True)
    highest = risks[0]
    if highest['risk'] >= 70:
        headline = f"Hoog risico op {highest['label'].lower()}"
        advice = 'Laat downloads gepauzeerd of op één worker draaien en controleer de logs voordat de wachtrij wordt hervat.'
    elif highest['risk'] >= 40:
        headline = f"Verhoogde kans op {highest['label'].lower()}"
        advice = 'Houd één worker aan, vermijd bulk-retries en volg de ontwikkeling in de komende uren.'
    else:
        headline = 'Geen direct operationeel risico'
        advice = 'Behoud de rustige downloadinstellingen en blijf de 24-uurs trend volgen.'
    return {
        'range': range_key, 'headline': headline, 'advice': advice,
        'confidence': 0.82 if trend.get('raw_sample_count', 0) >= 10 else 0.62,
        'queue_hours': queue_hours, 'risks': risks, 'health': health,
        'trend_summary': summary,
    }
