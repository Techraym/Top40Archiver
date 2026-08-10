from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any

import requests

from .ai_learning import complete_action, start_action
from .ai_model_runtime import ModelBusy, model_slot
from .ai_session_console import operator_context, scope_held
from .db import connect, now_iso
from .download_db import set_ai_provider_adjustment
from .download_metrics import provider_dashboard
from .providers import PROVIDER_CLASSES

MODEL_TIMEOUT_SECONDS = 30
MAX_COOLDOWN_MINUTES = 120
FIXED_FIRST_PROVIDER = "youtube"


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
            SET cooldown_until=?,
                status=CASE WHEN status='healthy' THEN 'limited' ELSE status END,
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
    return unhealthy or attempts >= 10


def _ask_qwen(snapshot: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "fixed_first_provider": FIXED_FIRST_PROVIDER,
        "goal": "YouTube blijft eerste bron; optimaliseer alleen fallbacks en concrete cooldowns",
        "downloads_24h": snapshot.get("downloads_24h"),
        "youtube_24h": snapshot.get("youtube_24h"),
        "youtube_music_24h": snapshot.get("youtube_music_24h"),
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
                "successes_24h": item.get("successes_24h"),
                "average_search_ms": item.get("average_search_ms"),
                "average_download_ms": item.get("average_download_ms"),
                "average_match_score": item.get("average_match_score"),
                "consecutive_errors": item.get("consecutive_errors"),
                "last_error_category": item.get("last_error_category"),
                "cooldown_until": item.get("cooldown_until"),
                "max_concurrent": item.get("max_concurrent"),
            }
            for item in snapshot.get("providers", [])
        ],
        "operator_guidance": operator_context("downloads"),
    }
    prompt = (
        "Je bent de lokale Top40Archiver provider-tuner. Directe YouTube is door de operator vastgezet als de "
        "EERSTE downloadbron. Je mag die positie, pacing of max_concurrent=1 nooit wijzigen. Analyseer uitsluitend "
        "de gemeten resultaten om de fallbackbronnen te ordenen en tijdelijke cooldowns voor concrete recente "
        "fouten te adviseren. Een YouTube-cooldown mag alleen bij een aantoonbare recente fout; na de cooldown wordt "
        "YouTube automatisch weer de eerste bron. Je mag GEEN accounts, cookies, CAPTCHA-omzeiling, proxyrotatie, "
        "rate-limit-bypass, shellcommando's of nieuwe providers voorstellen. Geef uitsluitend JSON: "
        '{"summary":"...","adjustments":[{"provider":"soundcloud","priority_adjustment":0,"cooldown_minutes":0,"reason":"..."}]}. '
        "priority_adjustment ligt tussen -20 en +20. Voor provider youtube wordt priority_adjustment altijd genegeerd. "
        "Een cooldown is maximaal 120 minuten en alleen toegestaan bij concrete recente fouten. Houd wijzigingen klein.\n\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    with model_slot("provider-ai", priority="background", wait_seconds=1.5):
        response = requests.post(
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
            json={
                "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "30m",
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 420},
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

    # Een oud AI-besluit uit de vroegere fallbackpolicy mag YouTube niet beïnvloeden.
    set_ai_provider_adjustment(FIXED_FIRST_PROVIDER, 0, "YouTube is vaste eerste downloadbron")

    if scope_held("downloads"):
        return {"ok": True, "action": "operator_hold", "snapshot": snapshot}
    if not _needs_ai(snapshot):
        return {
            "ok": True,
            "action": "no_model_needed",
            "reason": "Providerstatus is stabiel; YouTube blijft eerste bron en de vaste fallbackvolgorde blijft actief.",
            "snapshot": provider_dashboard(),
        }

    action_id = start_action(
        cycle_id=cycle_id,
        domain="downloads",
        problem_key="downloads:provider_mix",
        action="qwen_provider_tuning",
        reason="Fallbackproviders begrensd afstemmen terwijl YouTube vast de eerste downloadbron blijft.",
        before={"providers": snapshot.get("providers")},
        reversible=True,
    )
    try:
        suggestion = _ask_qwen(snapshot)
        applied: list[dict[str, Any]] = []
        by_name = {
            str(item.get("provider")): item
            for item in snapshot.get("providers", [])
        }
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
            if provider == FIXED_FIRST_PROVIDER:
                adjustment = 0

            reason = str(
                raw.get("reason")
                or suggestion.get("summary")
                or "Qwen fallback-provideradvies"
            )[:1000]
            set_ai_provider_adjustment(provider, adjustment, reason)

            try:
                cooldown = max(
                    0,
                    min(MAX_COOLDOWN_MINUTES, int(raw.get("cooldown_minutes") or 0)),
                )
            except (TypeError, ValueError):
                cooldown = 0
            recent_problem = (
                str(current.get("status") or "") in {"limited", "degraded", "offline"}
                or int(current.get("consecutive_errors") or 0) > 0
            )
            cooldown_until = (
                _extend_cooldown(provider, cooldown, reason)
                if cooldown and recent_problem
                else None
            )
            applied.append(
                {
                    "provider": provider,
                    "priority_adjustment": adjustment,
                    "cooldown_until": cooldown_until,
                    "reason": reason,
                }
            )

        # Ook wanneer Qwen iets anders teruggaf blijft deze invariant hard staan.
        set_ai_provider_adjustment(
            FIXED_FIRST_PROVIDER,
            0,
            "YouTube is vaste eerste downloadbron",
        )
        after = provider_dashboard()
        complete_action(
            action_id,
            success=True,
            after={"providers": after.get("providers")},
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
                "youtube_fixed_first": True,
                "youtube_max_concurrent": 1,
                "accounts_allowed": False,
                "cookies_allowed": False,
                "captcha_bypass_allowed": False,
                "proxy_rotation_allowed": False,
                "rate_limit_bypass_allowed": False,
            },
        }
    except ModelBusy as exc:
        complete_action(
            action_id,
            success=False,
            result={"error": str(exc), "reason": "operator/model slot heeft voorrang"},
            effect_score=0.0,
        )
        return {
            "ok": True,
            "action": "model_busy",
            "reason": str(exc),
            "snapshot": provider_dashboard(),
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
            "reason": "Qwen-provideradvies was tijdelijk niet beschikbaar; YouTube blijft eerste bron en de vaste coordinator werkt door.",
            "error": str(exc)[-1000:],
            "snapshot": provider_dashboard(),
        }
