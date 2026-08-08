from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from . import ai_operator_chat_legacy as _legacy
from .ai_model_runtime import ModelBusy, model_slot, runtime_status

MODEL = _legacy.MODEL
OLLAMA_URL = _legacy.OLLAMA_URL
CHAT_ALLOWED_ACTIONS = _legacy.CHAT_ALLOWED_ACTIONS
MAX_ACTIONS_PER_COMMAND = _legacy.MAX_ACTIONS_PER_COMMAND
MODEL_TIMEOUT_SECONDS = 120
PRIMARY_EVIDENCE_BYTES = 18_000
RETRY_EVIDENCE_BYTES = 8_000


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
    attempts_limit = 12 if retry else 28
    errors_limit = 12 if retry else 30
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
        evidence = dict(snapshot.get("download_evidence") or {})
        evidence["recent_provider_attempts"] = list(evidence.get("recent_provider_attempts") or [])[-attempts_limit:]
        evidence["recent_ai_actions"] = list(evidence.get("recent_ai_actions") or [])[-12:]
        base.update({
            "downloads": snapshot.get("downloads"),
            "download_evidence": evidence,
            "providers": snapshot.get("providers"),
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
    limit = RETRY_EVIDENCE_BYTES if retry else PRIMARY_EVIDENCE_BYTES
    evidence = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(evidence.encode("utf-8")) > limit:
        evidence = evidence.encode("utf-8")[:limit].decode("utf-8", "ignore") + "\n[bewijs begrensd door runtime]"
    command_text = command[:5000] if retry else command[:10000]
    prompt = f"""Je bent Qwen, lokale Top40Archiver diagnose-assistent.
Gebruik alleen het meegeleverde lokale bewijs. Geef geen verborgen redeneerstappen.
Geen vrije shell, geen audio verwijderen/overschrijven, geen cookies/CAPTCHA/proxy/rate-limit bypass.
MODE={mode}. In diagnose-modus MOET recommended_actions leeg zijn.
Adviseer uitsluitend acties uit: {json.dumps(sorted(CHAT_ALLOWED_ACTIONS))}.
Als bewijs onvoldoende is, zeg dat expliciet en adviseer geen mutatie.

OPDRACHT:
{command_text}

DOMEIN={domain}
LOKAAL_BEWIJS:
{evidence}

Retourneer UITSLUITEND één JSON-object met summary, diagnosis (array), evidence (array), recommended_actions (array van objects met action/reason), verification_plan (array)."""
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
                    "keep_alive": "30m",
                    "options": {"temperature": 0.1, "num_predict": 420 if retry else 700, "num_ctx": 8192},
                },
                timeout=90 if retry else MODEL_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise OperatorModelError("qwen_timeout", f"Qwen antwoordde niet binnen {'90' if retry else MODEL_TIMEOUT_SECONDS} seconden") from exc
    except ModelBusy as exc:
        raise OperatorModelError("model_busy", str(exc)) from exc
    except requests.RequestException as exc:
        raise OperatorModelError("ollama_http_error", str(exc)[-800:]) from exc
    text = str(response.json().get("response") or "")
    parsed = _json_payload(text)
    plan = _legacy._normalise_plan(parsed)
    plan["model_runtime"] = {
        "domain": domain,
        "retry": retry,
        "evidence_bytes": len(evidence.encode("utf-8")),
        "response_bytes": len(text.encode("utf-8")),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "num_ctx": 8192,
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
        "ollama_http_error": "De Ollama-aanroep mislukte",
    }
    return {
        "summary": f"{labels.get(code, 'Qwen kon de opdracht niet analyseren')}. Er zijn geen onbewezen mutaties uitgevoerd.",
        "diagnosis": [f"{code}: {detail}"],
        "evidence": [f"ollama.reachable={(snapshot.get('ollama') or {}).get('reachable')}", f"runtime={runtime_status()}"],
        "recommended_actions": actions,
        "verification_plan": ["Herhaal de analyse nadat de modelruntime beschikbaar is; gebruik dezelfde lokale evidence-policy."],
        "model_error_type": code,
        "model_error": detail,
    }


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
    # Preserve the old monkeypatch/test surface while routing through 1.16.14 logic.
    _legacy._ask_qwen = _ask_qwen
    _legacy._fallback_plan = _fallback_plan
    _legacy.collect_operator_evidence = collect_operator_evidence
    _legacy.log_session_event = log_session_event
    return _legacy.run_operator_command(command, mode)
