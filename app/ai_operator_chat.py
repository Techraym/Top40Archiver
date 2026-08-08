from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from . import ai_operator_chat_legacy as _legacy
from .ai_model_runtime import ModelBusy, model_slot, runtime_status
from .download_diagnostics import collect_download_diagnostics

MODEL = _legacy.MODEL
OLLAMA_URL = _legacy.OLLAMA_URL
CHAT_ALLOWED_ACTIONS = _legacy.CHAT_ALLOWED_ACTIONS
MAX_ACTIONS_PER_COMMAND = _legacy.MAX_ACTIONS_PER_COMMAND
MODEL_TIMEOUT_SECONDS = 120
PRIMARY_EVIDENCE_BYTES = 18_000
RETRY_EVIDENCE_BYTES = 8_000
DOWNLOAD_EVIDENCE_BYTES = 6_500
DOWNLOAD_RETRY_EVIDENCE_BYTES = 3_200
DOWNLOAD_MODEL_TIMEOUT_SECONDS = 75
DOWNLOAD_RETRY_TIMEOUT_SECONDS = 60


class OperatorModelError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _domain_for_command(command: str) -> str:
    text = str(command or "").casefold()
    if any(x in text for x in ("download", "provider", "youtube", "soundcloud", "audiomack", "audius", "bandcamp", "match", "retry")):
        return "downloads"
    if any(x in text for x in ("chart", "top 40", "tipparade", "week", "w32")):
        return "charts"
    if any(x in text for x in ("cover", "hoes", "artwork")):
        return "covers"
    if any(x in text for x in ("control room", "ui", "layout", "browser")):
        return "ui"
    if any(x in text for x in ("ollama", "qwen", "model", "ai")):
        return "ai"
    return "operations"


def _compact_errors(items: list[dict[str, Any]], domain: str, limit: int) -> list[dict[str, Any]]:
    needles = {
        "downloads": ("download", "provider", "youtube", "soundcloud", "audiomack", "audius", "bandcamp", "403", "429", "drm"),
        "charts": ("chart", "top40", "top 40", "tipparade", "freshness"),
        "covers": ("cover", "artwork"),
        "ui": ("control room", "ui", "render", "browser"),
        "ai": ("ollama", "qwen", "model", "timeout"),
        "operations": (),
    }.get(domain, ())
    selected = []
    for item in reversed(items or []):
        text = json.dumps(item, ensure_ascii=False).casefold()
        if not needles or any(n in text for n in needles):
            selected.append(item)
        if len(selected) >= limit:
            break
    return list(reversed(selected))


def _compact_snapshot(snapshot: dict[str, Any], command: str, *, retry: bool = False) -> tuple[dict[str, Any], str]:
    domain = _domain_for_command(command)
    errors_limit = 8 if retry else 16
    base: dict[str, Any] = {
        "generated_at": snapshot.get("generated_at"),
        "domain": domain,
        "ollama": snapshot.get("ollama"),
        "services": snapshot.get("services"),
        "database": snapshot.get("database"),
        "backup": snapshot.get("backup"),
        "policy": snapshot.get("policy"),
    }
    if domain == "downloads":
        diagnostics = collect_download_diagnostics(
            attempt_limit=120 if retry else 240,
            example_limit=5 if retry else 10,
        )
        base.update({
            "downloads": snapshot.get("downloads"),
            "download_diagnostics": diagnostics,
            "recent_errors": _compact_errors(snapshot.get("recent_errors") or [], domain, errors_limit),
        })
    elif domain == "charts":
        base.update({"charts": snapshot.get("charts"), "recent_errors": _compact_errors(snapshot.get("recent_errors") or [], domain, errors_limit)})
    elif domain == "covers":
        base.update({"covers": snapshot.get("covers"), "recent_errors": _compact_errors(snapshot.get("recent_errors") or [], domain, errors_limit)})
    elif domain == "ui":
        base.update({
            "charts": snapshot.get("charts"),
            "downloads": snapshot.get("downloads"),
            "covers": snapshot.get("covers"),
            "recent_errors": _compact_errors(snapshot.get("recent_errors") or [], domain, errors_limit),
        })
    elif domain == "ai":
        base.update({"model_runtime": runtime_status(), "recent_errors": _compact_errors(snapshot.get("recent_errors") or [], domain, errors_limit)})
    else:
        base.update({
            "downloads": snapshot.get("downloads"),
            "charts": snapshot.get("charts"),
            "covers": snapshot.get("covers"),
            "recent_errors": _compact_errors(snapshot.get("recent_errors") or [], domain, errors_limit),
        })
    return base, domain


def _json_payload(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        raise OperatorModelError("empty_response", "Qwen gaf een leeg antwoord terug")
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    candidates = [value]
    start, end = value.find("{"), value.rfind("}")
    if start >= 0 and end > start:
        candidates.append(value[start : end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            last_error = exc
    raise OperatorModelError("invalid_json", f"Qwen antwoord was geen geldig JSON-object: {last_error}")


def _call_qwen(command: str, snapshot: dict[str, Any], mode: str, *, retry: bool) -> dict[str, Any]:
    compact, domain = _compact_snapshot(snapshot, command, retry=retry)
    downloads = domain == "downloads"
    if downloads:
        limit = DOWNLOAD_RETRY_EVIDENCE_BYTES if retry else DOWNLOAD_EVIDENCE_BYTES
        command_limit = 1600 if retry else 2600
        timeout = DOWNLOAD_RETRY_TIMEOUT_SECONDS if retry else DOWNLOAD_MODEL_TIMEOUT_SECONDS
        num_predict = 180 if retry else 280
        num_ctx = 4096
    else:
        limit = RETRY_EVIDENCE_BYTES if retry else PRIMARY_EVIDENCE_BYTES
        command_limit = 5000 if retry else 10000
        timeout = 90 if retry else MODEL_TIMEOUT_SECONDS
        num_predict = 420 if retry else 700
        num_ctx = 8192

    evidence = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(evidence.encode("utf-8")) > limit:
        evidence = evidence.encode("utf-8")[:limit].decode("utf-8", "ignore") + "\n[bewijs begrensd door runtime]"
    command_text = command[:command_limit]
    prompt = f"""Je bent Qwen, lokale Top40Archiver diagnose-assistent.
Gebruik uitsluitend het meegeleverde lokale bewijs. Geef geen verborgen redeneerstappen.
Geen vrije shell, geen audio verwijderen/overschrijven, geen cookies/CAPTCHA/proxy/rate-limit bypass.
MODE={mode}. In diagnose-modus MOET recommended_actions leeg zijn.
Adviseer uitsluitend acties uit: {json.dumps(sorted(CHAT_ALLOWED_ACTIONS))}.
Een retry, requeue, zoekresultaat of gevonden kandidaat is geen downloadsukses.
Downloadsukses is alleen een completed job of provider attempt success=1.
Als bewijs onvoldoende is, zeg dat expliciet en adviseer geen mutatie.

OPDRACHT:
{command_text}

DOMEIN={domain}
LOKAAL_BEWIJS:
{evidence}

Retourneer UITSLUITEND één compact JSON-object met summary, diagnosis (array), evidence (array), recommended_actions (array van objects met action/reason), verification_plan (array)."""
    started = time.monotonic()
    try:
        with model_slot("operator-chat", priority="operator", wait_seconds=35):
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "think": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0.1, "num_predict": num_predict, "num_ctx": num_ctx},
                },
                timeout=timeout,
            )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise OperatorModelError("qwen_timeout", f"Qwen antwoordde niet binnen {timeout} seconden") from exc
    except ModelBusy as exc:
        raise OperatorModelError("model_busy", str(exc)) from exc
    except PermissionError as exc:
        raise OperatorModelError("model_runtime_permission", str(exc)[-800:]) from exc
    except requests.RequestException as exc:
        raise OperatorModelError("ollama_http_error", str(exc)[-800:]) from exc

    payload = response.json()
    text = str(payload.get("response") or "")
    parsed = _json_payload(text)
    plan = _legacy._normalise_plan(parsed)
    plan["model_runtime"] = {
        "domain": domain,
        "retry": retry,
        "evidence_bytes": len(evidence.encode("utf-8")),
        "response_bytes": len(text.encode("utf-8")),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "num_ctx": num_ctx,
        "num_predict": num_predict,
        "think": False,
        "prompt_eval_count": payload.get("prompt_eval_count"),
        "eval_count": payload.get("eval_count"),
        "ollama_total_duration_ns": payload.get("total_duration"),
    }
    return plan


def _ask_qwen(command: str, snapshot: dict[str, Any], mode: str) -> dict[str, Any]:
    first_error: OperatorModelError | None = None
    try:
        return _call_qwen(command, snapshot, mode, retry=False)
    except OperatorModelError as exc:
        first_error = exc
        if exc.code not in {"qwen_timeout", "invalid_json", "empty_response"}:
            raise
    try:
        plan = _call_qwen(command, snapshot, mode, retry=True)
        plan["model_runtime"]["first_attempt_error"] = first_error.code if first_error else None
        return plan
    except OperatorModelError as second:
        raise OperatorModelError(second.code, f"eerste poging: {first_error.code if first_error else 'onbekend'}; tweede poging: {second.detail}") from second


def _fallback_plan(command: str, snapshot: dict[str, Any], mode: str, error: Exception) -> dict[str, Any]:
    code = error.code if isinstance(error, OperatorModelError) else "qwen_error"
    detail = error.detail if isinstance(error, OperatorModelError) else str(error)[-900:]
    actions: list[dict[str, str]] = []
    lowered = command.casefold()
    if mode == "repair" and not (snapshot.get("ollama") or {}).get("reachable") and any(word in lowered for word in ("qwen", "ollama", "model", "ai")):
        actions.append({"action": "restart_ollama", "reason": "Ollama HTTP-API is lokaal niet bereikbaar."})
    labels = {
        "qwen_timeout": "Qwen liep tegen de tijdslimiet aan",
        "invalid_json": "Qwen gaf een ongeldig JSON-antwoord",
        "empty_response": "Qwen gaf geen antwoordtekst terug",
        "model_busy": "Qwen is tijdelijk bezet door een andere AI-taak",
        "model_runtime_permission": "De gedeelde Qwen-runtime heeft onjuiste bestandsrechten",
        "ollama_http_error": "De Ollama-aanroep mislukte",
    }
    evidence = [f"ollama.reachable={(snapshot.get('ollama') or {}).get('reachable')}", f"runtime={runtime_status()}"]
    if _domain_for_command(command) == "downloads":
        try:
            diag = collect_download_diagnostics(attempt_limit=120, example_limit=5)
            evidence.append(
                "deterministic_download_summary="
                + json.dumps(
                    {
                        "job_status": diag.get("job_status"),
                        "completed_jobs_24h": diag.get("completed_jobs_24h"),
                        "successful_provider_attempts_24h": diag.get("successful_provider_attempts_24h"),
                        "dominant_failure_stage": diag.get("dominant_failure_stage"),
                        "error_counts": diag.get("error_counts"),
                    },
                    ensure_ascii=False,
                )[:1800]
            )
        except Exception as diag_exc:
            evidence.append(f"download_diagnostics_error={str(diag_exc)[-400:]}")
    return {
        "summary": f"{labels.get(code, 'Qwen kon de opdracht niet analyseren')}. Er zijn geen onbewezen mutaties uitgevoerd.",
        "diagnosis": [f"{code}: {detail}"],
        "evidence": evidence,
        "recommended_actions": actions,
        "verification_plan": ["Herhaal de analyse nadat de modelruntime beschikbaar is; de downloader-evidence wordt deterministisch gecomprimeerd."],
        "model_error_type": code,
        "model_error": detail,
    }


# Upgrade the legacy route implementation in-place while keeping its tested
# policy, audit trail and safe-action executor.
_legacy._ask_qwen = _ask_qwen
_legacy._fallback_plan = _fallback_plan
_legacy.MODEL_TIMEOUT_SECONDS = MODEL_TIMEOUT_SECONDS
_legacy.OPERATOR_CHAT_HTML = _legacy.OPERATOR_CHAT_HTML.replace(
    "load();setInterval(load,5000);",
    "load();function autoRefresh(){if(document.hidden||document.querySelector('details[open]'))return;load()}setInterval(autoRefresh,15000);",
)

router = _legacy.router
action_precondition = _legacy.action_precondition
collect_operator_evidence = _legacy.collect_operator_evidence
log_session_event = _legacy.log_session_event
OperatorCommandIn = _legacy.OperatorCommandIn
operator_chat_status = _legacy.operator_chat_status
operator_chat_command = _legacy.operator_chat_command
operator_chat_page = _legacy.operator_chat_page
_metric_summary = _legacy._metric_summary
_normalise_plan = _legacy._normalise_plan


def run_operator_command(command: str, mode: str = "diagnose") -> dict[str, Any]:
    # Preserve the old monkeypatch/test surface while routing through 1.16.15 logic.
    _legacy._ask_qwen = _ask_qwen
    _legacy._fallback_plan = _fallback_plan
    _legacy.collect_operator_evidence = collect_operator_evidence
    _legacy.log_session_event = log_session_event
    return _legacy.run_operator_command(command, mode)
