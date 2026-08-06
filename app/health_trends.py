from __future__ import annotations

from statistics import mean
from typing import Any

from .health_engine import health_history


def health_trends(range_key: str = '24h') -> dict[str, Any]:
    hours = {'1h': 1, '24h': 24, '7d': 168}.get(range_key, 24)
    rows = health_history(hours, 2000)
    if not rows:
        return {'range': range_key, 'hours': hours, 'raw_sample_count': 0, 'summary': {'score_direction': 'stable', 'failed_change': 0}}
    scores = [float(row['score']) for row in rows]
    change = scores[-1] - scores[0]
    direction = 'up' if change > 2 else 'down' if change < -2 else 'stable'
    summary = {
        'score_average': round(mean(scores), 1),
        'score_minimum': int(min(scores)),
        'score_maximum': int(max(scores)),
        'score_direction': direction,
        'cpu_average': round(mean(float(row['cpu_percent']) for row in rows), 1),
        'memory_average': round(mean(float(row['memory_percent']) for row in rows), 1),
        'failed_change': int(rows[-1]['queue_failed']) - int(rows[0]['queue_failed']),
        'queue_average': round(mean(float(row['queue_pending']) for row in rows), 1),
    }
    return {'range': range_key, 'hours': hours, 'raw_sample_count': len(rows), 'summary': summary}
