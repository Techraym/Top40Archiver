from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any

import requests

from .ai_learning import complete_action, start_action
from .ai_session_console import operator_context, scope_held
from .db import connect, now_iso
from .download_db import provider_dashboard, set_ai_provider_adjustment
from .providers import PROVIDER_CLASSES

MODEL_TIMEOUT_SECONDS = 30
MAX_COOLDOWN_MINUTES = 120
YOUTUBE_FAMILY = {"youtube", "youtube_music"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _extend_cooldown(provider: str, minutes: int, reason: str) -> str | None:
    bounded = max(0, min(MAX_COOLDOWN_MINUTES, int(minutes)))
    if bounded <= 0:
        return None
    target = _now() + timedelta(minutes=bounded)
    with connect() as con:
        row = con.execute(
            "SELECT cooldown_until,status FROM download_provider_state WHERE provider=?",
            (provider,),
        ).fetchone()
        if row is None:
            return None
        current = _parse_time(row["cooldown_until"])
        if current and current > target:
            target = current
        con.execute(
            """
            UPDATE download_provider_state
            SET cooldown_until=?,status=CASE WHEN status='healthy' THEN 'limited' ELSE status END,
                ai_last_decision=?,updated_at=?
            WHERE provider=?
            """,
            (target.isoformat(), str(reason or "")[:1000], now_iso(), provider),
        )
    return target.isoformat()


def _needs_ai(snapshot: dict[str, Any]) -> bool:
    providers = snapshot.get("providers") or []
    attempts = sum(int(item.get("attempts_24h") or 0) for item in providers)
    unhealthy = any(
        item.get("status") in {"limited", "degraded", "offline"}
        or int(item.get("consecutive_errors") or 0) > 0
        for item in providers
    )
    dependency = float(snapshot.get("youtube_dependency_percent") or 0)
    return unhealthy or attempts >= 10 or (attempts >= 5 and dependency >= 10)


def _ask_qwen(snapshot: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "goal": "YouTube-family dependency below 10 percent without bypassing provider safeguards",
        "youtube_dependency_percent": snapshot.get("youtube_dependency_percent"),
        "providers": [
            {
                "provider": item.get("provider"),
                "enabled": bool(item.get("enabled")),
                "priority": item.get("priority"),
                "current_ai_adjustment": item.get("ai_priority_adjustment"),
                "status": item.get("status"),
                "health_score": item.get("calculated_health_score"),
                "success_rate_24h": item.get("success_rate_24h"),
                "attempts_24h": item.get("attempts_24h"),
                "average_search_ms": item.get("average_search_ms"),
                "average_download_ms": item.get("average_download_ms"),
                "average_match_score": item.get("average_match_score"),
                "consecutive_errors": item.get("consecutive_errors"),
                "cooldown_until": item.get("cooldown_until"),
                "max_concurrent": item.get("max_concurrent"),
            }
            for item in snapshot.get("providers", [])
        ],
        "operator_guidance": operator_context("downloads"),
    }
    prompt = (
        "Je bent de lokale Top40Archiver provider-tuning assistent. Analyseer alleen de meegegeven gemeten providerdata. "
        "De vaste coordinator en circuit breakers blijven leidend. Je mag GEEN accounts, cookies, captcha-omzeiling, "
        "proxyrotatie, rate-limit-bypass, shellcommando's of nieuwe providers voorstellen. YouTube Music en YouTube "
        "blijven fallback en mogen nooit eerder worden geplaatst dan niet-YouTube-providers. Geef uitsluitend JSON: "
        '{"summary":"...","adjustments":[{"provider":"soundcloud","priority_adjustment":0,"cooldown_minutes":0,"reason":"..."}]}. '
        "priority_adjustment ligt tussen -20 en +20; positief betekent later proberen. Een cooldown mag alleen worden "
        "voorgesteld bij concrete recente fouten en maximaal 120 minuten. Houd wijzigingen klein en laat een provider "
        "ongewijzigd als er onvoldoende bewijs is.\n\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    response = requests.post(
        os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        json={
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": 0.1, "num_predict": 512},
        },
        timeout=MODEL_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = json.loads(str(response.json().get("response") or "{}"))
    if not isinstance(payload, dict):
        raise ValueError("Qwen provideradvies is geen JSON-object")
    return payload


def run_provider_ai_tuning(cycle_id: str) -> dict[str, Any]:
    snapshot = provider_dashboard()
    if scope_held("downloads"):
        return {"ok": True, "action": "operator_hold", "snapshot": snapshot}
    if not _needs_ai(snapshot):
        return {
            "ok": True,
            "action": "no_model_needed",
            "reason": "Nog onvoldoende providerbewijs of geen providerafwijking; vaste coordinator blijft actief.",
            "snapshot": snapshot,
        }

    action_id = start_action(
        cycle_id=cycle_id,
        domain="downloads",
        problem_key="downloads:provider_mix",
        action="qwen_provider_tuning",
        reason="Gemeten providerresultaten en YouTube-afhankelijkheid begrensd laten meewegen in de provider-volgorde.",
        before={
            "youtube_dependency_percent": snapshot.get("youtube_dependency_percent"),
            "providers": snapshot.get("providers"),
        },
        reversible=True,
    )
    try:
        suggestion = _ask_qwen(snapshot)
        applied: list[dict[str, Any]] = []
        by_name = {str(item.get("provider")): item for item in snapshot.get("providers", [])}
        for raw in suggestion.get("adjustments") or []:
            if not isinstance(raw, dict):
                continue
            provider = str(raw.get("provider") or "")
            current = by_name.get(provider)
            if provider not in PROVIDER_CLASSES or current is None or not bool(current.get("enabled")):
                continue
            try:
                adjustment = max(-20, min(20, int(raw.get("priority_adjustment") or 0)))
            except (TypeError, ValueError):
                adjustment = 0
            # YouTube-family blijft altijd fallback: AI mag die alleen gelijk houden of later zetten.
            if provider in YOUTUBE_FAMILY:
                adjustment = max(0, adjustment)
            reason = str(raw.get("reason") or suggestion.get("summary") or "Qwen provideradvies")[:1000]
            set_ai_provider_adjustment(provider, adjustment, reason)

            try:
                cooldown = max(0, min(MAX_COOLDOWN_MINUTES, int(raw.get("cooldown_minutes") or 0)))
            except (TypeError, ValueError):
                cooldown = 0
            recent_problem = (
                str(current.get("status") or "") in {"limited", "degraded", "offline"}
                or int(current.get("consecutive_errors") or 0) > 0
            )
            cooldown_until = _extend_cooldown(provider, cooldown, reason) if cooldown and recent_problem else None
            applied.append(
                {
                    "provider": provider,
                    "priority_adjustment": adjustment,
                    "cooldown_until": cooldown_until,
                    "reason": reason,
                }
            )

        after = provider_dashboard()
        complete_action(
            action_id,
            success=True,
            after={
                "youtube_dependency_percent": after.get("youtube_dependency_percent"),
                "providers": after.get("providers"),
            },
            result={"summary": suggestion.get("summary"), "applied": applied},
            effect_score=0.2 if applied else 0.0,
        )
        return {
            "ok": True,
            "action": "qwen_provider_tuning",
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
            "summary": str(suggestion.get("summary") or "")[:1500],
            "applied": applied,
            "snapshot": after,
            "policy": {
                "accounts_allowed": False,
                "cookies_allowed": False,
                "captcha_bypass_allowed": False,
                "proxy_rotation_allowed": False,
                "rate_limit_bypass_allowed": False,
                "youtube_can_be_promoted_before_primary": False,
            },
        }
    except Exception as exc:
        complete_action(
            action_id,
            success=False,
            result={"error": str(exc)[-1500:]},
            effect_score=0.0,
        )
        return {
            "ok": True,
            "action": "model_unavailable",
            "reason": "Qwen-provideradvies was tijdelijk niet beschikbaar; de vaste coordinator blijft zonder wijziging doorwerken.",
            "error": str(exc)[-1000:],
            "snapshot": snapshot,
        }
