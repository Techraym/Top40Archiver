from __future__ import annotations

import json
import os
from typing import Any

import requests

from .ai_learning import complete_action, start_action
from .ai_model_runtime import ModelBusy, model_slot
from .ai_session_console import operator_context, scope_held
from .download_concurrency import (
    DEFAULT_DOWNLOAD_WORKERS,
    MAX_DOWNLOAD_WORKERS,
    evidence_worker_ceiling,
    hard_worker_ceiling,
    set_ai_download_workers,
    system_capacity_snapshot,
    system_worker_ceiling,
    worker_state,
)
from .download_metrics import provider_dashboard

MODEL_TIMEOUT_SECONDS = 25


def _ask_qwen(
    snapshot: dict[str, Any],
    state: dict[str, Any],
    evidence_ceiling: int,
    system: dict[str, Any],
    hard_ceiling: int,
) -> dict[str, Any]:
    providers = [
        {
            "provider": item.get("provider"),
            "status": item.get("status"),
            "attempts_24h": item.get("attempts_24h"),
            "successes_24h": item.get("successes_24h"),
            "success_rate_24h": item.get("success_rate_24h"),
            "average_download_ms": item.get("average_download_ms"),
            "consecutive_errors": item.get("consecutive_errors"),
            "active_workers": item.get("active_workers"),
            "max_concurrent": item.get("max_concurrent"),
        }
        for item in snapshot.get("providers", [])
    ]
    compact = {
        "worker_policy": {
            "default": DEFAULT_DOWNLOAD_WORKERS,
            "absolute_maximum": MAX_DOWNLOAD_WORKERS,
            "current": state,
            "evidence_ceiling": evidence_ceiling,
            "system_ceiling": system_worker_ceiling(system),
            "hard_ceiling": hard_ceiling,
        },
        "jobs": snapshot.get("jobs") or {},
        "completed_downloads_24h": snapshot.get("downloads_24h"),
        "youtube_dependency_percent": snapshot.get("youtube_dependency_percent"),
        "system": system,
        "providers": providers,
        "operator_guidance": operator_context("downloads"),
    }
    prompt = (
        "Je bent de lokale Top40Archiver concurrency-tuner. Kies uitsluitend het aantal GELIJKTIJDIGE GLOBALE "
        "downloadjobs. Normaal zijn het 2. Je mag alleen opschalen wanneer echte end-to-end downloads aantoonbaar "
        "slagen, er voldoende wachtrij is en de host voldoende CPU/geheugenruimte heeft. Kies bij twijfel 2. "
        "Je mag nooit boven hard_ceiling of absoluut 6 uitkomen. Providerlimieten zijn onafhankelijk: YouTube en "
        "YouTube Music blijven maximaal 1 gelijktijdige provideractie en mogen niet worden verruimd. Je mag geen "
        "accounts, cookies, CAPTCHA-omzeiling, proxyrotatie, rate-limit-bypass, shellcommando's of verwijdering/"
        "overschrijven van audio voorstellen. Geef uitsluitend JSON in exact deze vorm: "
        '{"download_workers":2,"reason":"korte reden gebaseerd op meetdata"}.\n\n'
        + json.dumps(compact, ensure_ascii=False)
    )

    with model_slot("download-concurrency-ai", priority="background", wait_seconds=1.5):
        response = requests.post(
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
            json={
                "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "30m",
                "think": False,
                "options": {"temperature": 0.05, "num_predict": 160},
            },
            timeout=MODEL_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    payload = json.loads(str(response.json().get("response") or "{}"))
    if not isinstance(payload, dict):
        raise ValueError("Qwen concurrency-advies is geen JSON-object")
    return payload


def run_download_concurrency_ai(cycle_id: str) -> dict[str, Any]:
    snapshot = provider_dashboard()
    state = worker_state()
    evidence_ceiling = evidence_worker_ceiling(snapshot)
    system = system_capacity_snapshot()
    system_ceiling = system_worker_ceiling(system)
    hard_ceiling = hard_worker_ceiling(snapshot, system)

    if scope_held("downloads"):
        return {
            "ok": True,
            "action": "operator_hold",
            "workers": state,
            "hard_ceiling": hard_ceiling,
        }

    # Hard evidence/system rules always win immediately, even before a model call.
    if int(state.get("effective") or DEFAULT_DOWNLOAD_WORKERS) > hard_ceiling:
        state = set_ai_download_workers(
            hard_ceiling,
            "Automatisch teruggeschakeld door gemeten evidence-/systeemgrens.",
        )

    if hard_ceiling <= DEFAULT_DOWNLOAD_WORKERS:
        if state.get("ai_active") and int(state.get("ai_target") or 2) != 2:
            state = set_ai_download_workers(
                DEFAULT_DOWNLOAD_WORKERS,
                "Onvoldoende bewijs of systeemruimte voor meer dan twee downloadjobs.",
            )
        return {
            "ok": True,
            "action": "fixed_two_workers",
            "reason": "Opschalen is nog niet verdiend door end-to-end succesdata of systeemruimte.",
            "workers": state,
            "evidence_ceiling": evidence_ceiling,
            "system_ceiling": system_ceiling,
            "hard_ceiling": hard_ceiling,
            "system": system,
        }

    action_id = start_action(
        cycle_id=cycle_id,
        domain="downloads",
        problem_key="downloads:global_concurrency",
        action="qwen_download_worker_tuning",
        reason="Globale downloadconcurrency begrensd afstemmen op echte successen, backlog en hostbelasting.",
        before={
            "workers": state,
            "evidence_ceiling": evidence_ceiling,
            "system_ceiling": system_ceiling,
            "hard_ceiling": hard_ceiling,
            "downloads_24h": snapshot.get("downloads_24h"),
            "jobs": snapshot.get("jobs"),
            "system": system,
        },
        reversible=True,
    )
    try:
        suggestion = _ask_qwen(snapshot, state, evidence_ceiling, system, hard_ceiling)
        try:
            requested = int(suggestion.get("download_workers") or DEFAULT_DOWNLOAD_WORKERS)
        except (TypeError, ValueError):
            requested = DEFAULT_DOWNLOAD_WORKERS
        requested = max(DEFAULT_DOWNLOAD_WORKERS, min(MAX_DOWNLOAD_WORKERS, requested))
        applied = max(DEFAULT_DOWNLOAD_WORKERS, min(requested, hard_ceiling))
        reason = str(suggestion.get("reason") or "Qwen concurrency-advies")[:1000]
        after = set_ai_download_workers(applied, reason)
        complete_action(
            action_id,
            success=True,
            after={
                "workers": after,
                "requested": requested,
                "applied": applied,
                "hard_ceiling": hard_ceiling,
            },
            result={"reason": reason},
            effect_score=0.2 if applied != int(state.get("effective") or 2) else 0.0,
        )
        return {
            "ok": True,
            "action": "qwen_download_worker_tuning",
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
            "requested": requested,
            "applied": applied,
            "workers": after,
            "evidence_ceiling": evidence_ceiling,
            "system_ceiling": system_ceiling,
            "hard_ceiling": hard_ceiling,
            "system": system,
            "reason": reason,
            "policy": {
                "default_workers": DEFAULT_DOWNLOAD_WORKERS,
                "absolute_max_workers": MAX_DOWNLOAD_WORKERS,
                "youtube_provider_max_concurrent_unchanged": True,
                "audio_delete_allowed": False,
                "overwrite_existing_audio_allowed": False,
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
            "workers": worker_state(),
            "hard_ceiling": hard_ceiling,
        }
    except Exception as exc:
        complete_action(
            action_id,
            success=False,
            result={"error": str(exc)[-1200:]},
            effect_score=0.0,
        )
        return {
            "ok": True,
            "action": "model_unavailable",
            "reason": "Qwen concurrency-advies tijdelijk niet beschikbaar; coordinator blijft veilig begrenzen.",
            "error": str(exc)[-1000:],
            "workers": worker_state(),
            "hard_ceiling": hard_ceiling,
        }
