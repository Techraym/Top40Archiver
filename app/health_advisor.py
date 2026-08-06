from __future__ import annotations

from typing import Any

from .health_engine import health_events, latest_health
from .health_trends import build_health_trends


def _priority(level: str) -> int:
    return {"critical": 0, "warning": 1, "info": 2}.get(level, 3)


def build_health_advice(range_key: str = "24h") -> dict[str, Any]:
    health = latest_health()
    trends = build_health_trends(range_key)
    events = health_events(50)
    advice: list[dict[str, Any]] = []

    def add(
        key: str,
        level: str,
        title: str,
        explanation: str,
        action: str,
        confidence: float,
    ) -> None:
        advice.append(
            {
                "key": key,
                "level": level,
                "title": title,
                "explanation": explanation,
                "action": action,
                "confidence": round(max(0.0, min(1.0, confidence)), 2),
            }
        )

    score = int(health.get("score") or 0)
    if score < 65:
        add(
            "health-critical",
            "critical",
            "Systeem eerst stabiliseren",
            health.get("diagnosis") or "De gezondheidsscore is kritisch.",
            "Laat nieuwe downloads gepauzeerd en behandel eerst de kritieke health-events.",
            0.98,
        )
    elif score < 85:
        add(
            "health-attention",
            "warning",
            "Gezondheid vraagt aandacht",
            health.get("diagnosis")
            or "Een of meer onderdelen zitten buiten de normale grens.",
            "Los de belangrijkste waarschuwing op voordat de wachtrij wordt versneld.",
            0.92,
        )

    disk_percent = float(health.get("disk_percent") or 0)
    if disk_percent >= 90:
        add(
            "storage",
            "critical" if disk_percent >= 97 else "warning",
            "Opslagruimte bewaken",
            f"De muziekopslag is voor {disk_percent:.1f}% gebruikt en heeft "
            f"{health.get('disk_free_gb')} GB vrij.",
            "Maak ruimte vrij of vergroot de opslag voordat nieuwe historische batches starten.",
            0.99,
        )

    workers = int(health.get("worker_count") or 1)
    if workers > 1:
        add(
            "workers",
            "warning",
            "Downloadparalleliteit beperken",
            f"Er zijn {workers} workers ingesteld. Na eerdere problemen is één worker de veilige standaard.",
            "Zet download_workers op 1 en verhoog alleen na een langere stabiele periode.",
            0.96,
        )

    failed = int(health.get("queue_failed") or 0)
    if failed >= 10:
        add(
            "failed",
            "warning",
            "Mislukte downloads analyseren",
            f"Er staan {failed} mislukte downloads geregistreerd.",
            "Open Live Logs en AI Operations, groepeer de foutoorzaken en probeer niet alles tegelijk opnieuw.",
            0.94,
        )

    summary = trends.get("summary") or {}
    direction = summary.get("direction")
    if direction == "falling":
        add(
            "trend-falling",
            "warning",
            "Gezondheid daalt",
            trends.get("diagnosis")
            or "De gezondheidsscore daalt in de gekozen periode.",
            "Verlaag belasting en controleer welke metriek tegelijk verslechtert.",
            0.88,
        )
    elif direction == "rising" and score >= 85:
        add(
            "trend-rising",
            "info",
            "Hersteltrend bevestigd",
            trends.get("diagnosis") or "De gezondheid verbetert.",
            "Behoud de huidige worker- en retryinstellingen totdat deze trend minimaal 24 uur stabiel blijft.",
            0.82,
        )

    recent_critical = [event for event in events if event.get("severity") == "critical"]
    if recent_critical:
        add(
            "critical-events",
            "critical",
            "Kritieke gebeurtenissen aanwezig",
            f"Er zijn {len(recent_critical)} recente kritieke health-events.",
            "Behandel de nieuwste kritieke gebeurtenis voordat automatische herstelacties worden vrijgegeven.",
            0.97,
        )

    if not advice:
        add(
            "stable",
            "info",
            "Systeem stabiel",
            "De actuele metingen en trendanalyse tonen geen directe operationele risico's.",
            "Laat één downloadworker actief en blijf de 24-uurs trend volgen.",
            0.86,
        )

    advice.sort(key=lambda item: (_priority(item["level"]), -item["confidence"]))
    return {
        "range": range_key,
        "score": score,
        "status": health.get("status"),
        "headline": advice[0],
        "advice": advice,
        "health": health,
        "trend": trends,
    }
