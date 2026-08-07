from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .ai_learning import complete_action, start_action
from .config import APP_DIR, DATA_DIR
from .dev_assistant import create_workspace, save_patch, validate_workspace, workspace_status

STATE_FILE = DATA_DIR / "ai" / "code-repair-state.json"
BACKUP_DIR = DATA_DIR / "ai" / "code-repair" / "file-backups"
ALLOWED_PRODUCTION_PREFIX = "app/"
ALLOWED_PRODUCTION_SUFFIXES = {".py"}
BLOCKED_PRODUCTION_FILES = {
    "app/ai_code_repair.py",
    "app/ai_code_improvement.py",
    "app/ai_learning.py",
    "app/ai_learning_api.py",
    "app/ai_memory.py",
    "app/ai_recovery_entry.py",
    "app/ai_platform.py",
    "app/ai_sidecar.py",
    "app/ai_control_room.py",
    "app/ai_ui_designer.py",
    "app/ai_update_handoff.py",
    "app/dev_assistant.py",
    "app/dev_assistant_api.py",
    "app/backup_health.py",
    "app/safe_temp_cleanup.py",
    "app/ai_storage_recovery.py",
    "app/service_watchdog.py",
    "app/config.py",
    "app/db.py",
}
SERVICES = (
    "top40-archiver-web.service",
    "top40-archiver-download.service",
    "top40-archiver-ai.service",
    "top40-archiver-cover-art.service",
    "top40-archiver-history.service",
    "top40-archiver-check.service",
)
EXCEPTION_RE = re.compile(
    r"(Traceback \(most recent call last\)|(?:Attribute|Type|Key|Name|Value|Runtime|Assertion|Syntax|Import|ModuleNotFound|UnboundLocal)Error:|Internal Server Error)",
    re.I,
)
SOURCE_RE = re.compile(r"/opt/top40-archiver/(app/[A-Za-z0-9_./-]+\.py)")
VERIFY_MINUTES = 10
REPAIR_COOLDOWN_MINUTES = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": {}, "active": None}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _journal(since: str = "20 minutes ago", lines: int = 1200) -> str:
    cmd = ["journalctl", "--no-pager", "--since", since, "-n", str(lines), "-o", "short-iso"]
    for unit in SERVICES:
        cmd.extend(["-u", unit])
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    return done.stdout[-300_000:]


def _fingerprint(block: str) -> str:
    normalized = re.sub(r"\b\d+\b", "#", " ".join(block.split()).casefold())[-4000:]
    return hashlib.sha256(normalized.encode("utf-8", "ignore")).hexdigest()[:24]


def _exception_candidate(log: str) -> dict | None:
    lines = log.splitlines()
    hits = [i for i, line in enumerate(lines) if EXCEPTION_RE.search(line)]
    if not hits:
        return None
    index = hits[-1]
    start = max(0, index - 35)
    end = min(len(lines), index + 25)
    block = "\n".join(lines[start:end])
    files = []
    for path in SOURCE_RE.findall(block):
        if path not in files:
            files.append(path)
    if not files:
        return None
    return {"fingerprint": _fingerprint(block), "evidence": block[-30_000:], "files": files[:4]}


def _read_sources(files: list[str]) -> str:
    chunks: list[str] = []
    budget = 80_000
    for rel in files:
        path = APP_DIR / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:35_000]
        part = f"\n### {rel}\n{text}\n"
        if sum(len(x) for x in chunks) + len(part) > budget:
            break
        chunks.append(part)
    return "".join(chunks)


def _ask_model(candidate: dict) -> str:
    prompt = (
        "Je bent de autonome Top40Archiver code-repair worker. Herstel uitsluitend de aangetoonde runtimefout. "
        "Maak de kleinst mogelijke veilige wijziging. Verander geen downloadbestanden, database-inhoud, secrets, "
        "systemd, updatebeleid of beveiligingsregels. Geef UITSLUITEND een unified git diff die met git apply werkt; "
        "geen markdown en geen uitleg. Als de fout niet veilig aantoonbaar uit deze broncode kan worden hersteld, antwoord NO_PATCH.\n\n"
        "FOUTBEWIJS:\n" + candidate["evidence"] + "\n\nBRONCODE:\n" + _read_sources(candidate["files"])
    )
    response = requests.post(
        os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        json={"model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"), "prompt": prompt, "stream": False, "keep_alive": "30m"},
        timeout=120,
    )
    response.raise_for_status()
    text = str(response.json().get("response") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:diff)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _safe_touched_files(status: dict) -> list[str]:
    files = list((status.get("proposal") or {}).get("files") or [])
    if not files:
        raise ValueError("patch wijzigt geen bestanden")
    for item in files:
        path = Path(item)
        if not item.startswith(ALLOWED_PRODUCTION_PREFIX) or path.suffix.lower() not in ALLOWED_PRODUCTION_SUFFIXES:
            raise ValueError(f"autonome productiepatch niet toegestaan voor {item}")
        if item in BLOCKED_PRODUCTION_FILES:
            raise ValueError(f"AI-beheer- of veiligheidsbestand is niet autonoom wijzigbaar: {item}")
        if ".." in path.parts or any(part in {"downloads", "venv", ".git"} for part in path.parts):
            raise ValueError(f"geblokkeerd patchpad: {item}")
    return files


def _verified_version_backup() -> str:
    done = subprocess.run(["/usr/local/sbin/top40-version-backup"], capture_output=True, text=True, timeout=180, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-2000:] or "version-backup mislukt")
    path = done.stdout.strip().splitlines()[-1].strip()
    if not path or not (Path(path) / "BACKUP_OK").is_file():
        raise RuntimeError("version-backup heeft geen BACKUP_OK")
    return path


def _restart_runtime() -> dict:
    results = {}
    for unit in ("top40-archiver-web.service", "top40-archiver-download.service", "top40-archiver-ai.service"):
        done = subprocess.run(["systemctl", "restart", unit], capture_output=True, text=True, timeout=90, check=False)
        results[unit] = done.returncode == 0
    return results


def _health() -> bool:
    for url in ("http://127.0.0.1:8040/health", "http://127.0.0.1:8041/healthz", "http://127.0.0.1:8042/healthz"):
        try:
            response = requests.get(url, timeout=6)
            if not response.ok:
                return False
        except Exception:
            return False
    return True


def _promote(workspace_id: str, fingerprint: str) -> dict:
    status = workspace_status(workspace_id)
    validation = status.get("validation") or {}
    if not validation.get("ok"):
        raise ValueError("patch is niet volledig gevalideerd")
    files = _safe_touched_files(status)
    version_backup = _verified_version_backup()
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    local_backup = BACKUP_DIR / f"{stamp}-{fingerprint}"
    local_backup.mkdir(parents=True, exist_ok=False)
    source = DATA_DIR / "ai" / "development" / "workspaces" / workspace_id / "source"

    for rel in files:
        old = APP_DIR / rel
        saved = local_backup / rel
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, saved)
    for rel in files:
        patched = source / rel
        target = APP_DIR / rel
        shutil.copy2(patched, target)

    compile_result = subprocess.run(
        [str(APP_DIR / "venv/bin/python"), "-m", "compileall", "-q", str(APP_DIR / "app")],
        capture_output=True, text=True, timeout=120, check=False,
    )
    runtime = _restart_runtime()
    time.sleep(3)
    ok = compile_result.returncode == 0 and all(runtime.values()) and _health()
    if not ok:
        for rel in files:
            shutil.copy2(local_backup / rel, APP_DIR / rel)
        _restart_runtime()
        raise RuntimeError("canary-healthcheck faalde; productiecode is direct teruggezet")
    return {"ok": True, "files": files, "version_backup": version_backup, "file_backup": str(local_backup), "runtime": runtime}


def _rollback_active(active: dict) -> dict:
    backup = Path(str(active.get("file_backup") or ""))
    files = list(active.get("files") or [])
    if not backup.is_dir() or not files:
        return {"ok": False, "reason": "file_backup_missing"}
    for rel in files:
        shutil.copy2(backup / rel, APP_DIR / rel)
    runtime = _restart_runtime()
    time.sleep(2)
    return {"ok": all(runtime.values()) and _health(), "runtime": runtime}


def _verify_active(state: dict) -> dict | None:
    active = state.get("active")
    if not isinstance(active, dict):
        return None
    promoted_at = datetime.fromisoformat(str(active["promoted_at"]))
    if promoted_at.tzinfo is None:
        promoted_at = promoted_at.replace(tzinfo=timezone.utc)
    log = _journal(promoted_at.isoformat(), 1500)
    candidate = _exception_candidate(log)
    same_error = bool(candidate and candidate["fingerprint"] == active.get("fingerprint"))
    if same_error or not _health():
        rollback = _rollback_active(active)
        complete_action(int(active["action_id"]), success=False, after={"same_error": same_error, "health": _health()}, result={"rollback": rollback}, effect_score=-1.0)
        state["active"] = None
        _save_state(state)
        return {"status": "rolled_back", "same_error": same_error, "rollback": rollback}
    if _now() - promoted_at >= timedelta(minutes=VERIFY_MINUTES):
        complete_action(int(active["action_id"]), success=True, after={"health": True, "error_recurred": False}, result={"verified_minutes": VERIFY_MINUTES}, effect_score=1.0)
        state["active"] = None
        _save_state(state)
        return {"status": "verified", "minutes": VERIFY_MINUTES}
    return {"status": "canary", "minutes_remaining": max(0, VERIFY_MINUTES - int((_now() - promoted_at).total_seconds() // 60))}


def run_code_repair(cycle_id: str) -> dict:
    state = _load_state()
    verification = _verify_active(state)
    if state.get("active"):
        return {"ok": True, "action": "verify_existing_patch", "verification": verification}

    candidate = _exception_candidate(_journal())
    if not candidate:
        return {"ok": True, "action": "none", "verification": verification}

    seen = state.setdefault("seen", {}).setdefault(candidate["fingerprint"], {"samples": 0})
    sample_hash = hashlib.sha256(candidate["evidence"].encode("utf-8", "ignore")).hexdigest()
    if seen.get("last_sample") != sample_hash:
        seen["samples"] = int(seen.get("samples") or 0) + 1
        seen["last_sample"] = sample_hash
    seen["last_seen"] = _now().isoformat()
    _save_state(state)

    # Als de eerste waarneming al een volledig gevalideerde sandboxpatch opleverde,
    # hoeft de tweede onafhankelijke foutwaarneming niet opnieuw op Ollama/tests te
    # wachten. De bestaande patch kan dan direct naar de backup+canary-fase.
    cached_workspace = str(seen.get("validated_workspace") or "")
    if cached_workspace and int(seen.get("samples") or 0) >= 2:
        try:
            cached = workspace_status(cached_workspace)
            if (cached.get("validation") or {}).get("ok"):
                promote_id = start_action(
                    cycle_id=cycle_id,
                    domain="code",
                    problem_key=f"code:{candidate['fingerprint']}",
                    action="promote_validated_patch",
                    reason="Tweede onafhankelijke waarneming van dezelfde fout; eerder gevalideerde sandboxpatch wordt direct als canary getest.",
                    subject=candidate["fingerprint"],
                    before={"workspace": cached_workspace, "samples": seen["samples"]},
                    reversible=True,
                )
                promotion = _promote(cached_workspace, candidate["fingerprint"])
                seen.pop("validated_workspace", None)
                state["active"] = {
                    "fingerprint": candidate["fingerprint"],
                    "workspace_id": cached_workspace,
                    "action_id": promote_id,
                    "promoted_at": _now().isoformat(),
                    "files": promotion["files"],
                    "file_backup": promotion["file_backup"],
                    "version_backup": promotion["version_backup"],
                }
                _save_state(state)
                return {"ok": True, "action": "promoted_canary", "candidate": candidate["fingerprint"], "promotion": promotion, "reused_validated_workspace": True}
            seen.pop("validated_workspace", None)
        except Exception:
            seen.pop("validated_workspace", None)

    previous = seen.get("last_attempt")
    if previous:
        try:
            parsed = datetime.fromisoformat(str(previous))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if _now() - parsed < timedelta(minutes=REPAIR_COOLDOWN_MINUTES):
                return {"ok": True, "action": "cooldown", "candidate": candidate["fingerprint"], "samples": seen["samples"]}
        except ValueError:
            pass

    # Eén fout wordt direct geanalyseerd. Automatische productiepromotie vereist
    # twee onafhankelijke foutwaarnemingen zodat een eenmalige ruisregel geen code wijzigt.
    analysis_id = start_action(
        cycle_id=cycle_id,
        domain="code",
        problem_key=f"code:{candidate['fingerprint']}",
        action="analyze_and_validate_patch",
        reason="Herhaalde runtimefout automatisch analyseren en in sandbox reproduceren/valideren.",
        subject=candidate["fingerprint"],
        before={"files": candidate["files"], "samples": seen["samples"]},
    )
    seen["last_attempt"] = _now().isoformat()
    try:
        patch = _ask_model(candidate)
        if patch == "NO_PATCH" or "diff --git" not in patch:
            complete_action(analysis_id, success=False, result={"reason": "model_no_safe_patch"}, effect_score=0.0)
            _save_state(state)
            return {"ok": True, "action": "no_safe_patch", "candidate": candidate["fingerprint"]}
        workspace = create_workspace(f"Auto repair {candidate['fingerprint']}", candidate["evidence"])
        save_patch(workspace["id"], patch, "Autonoom herstel van geobserveerde runtimefout")
        validation = validate_workspace(workspace["id"])
        valid = bool(validation.get("ok"))
        complete_action(analysis_id, success=valid, after={"workspace": workspace["id"]}, result={"validation": valid}, effect_score=0.6 if valid else 0.0)
        if not valid:
            seen.pop("validated_workspace", None)
            _save_state(state)
            return {"ok": True, "action": "validation_failed", "workspace": workspace["id"], "samples": seen["samples"]}
        if int(seen.get("samples") or 0) < 2:
            seen["validated_workspace"] = workspace["id"]
            _save_state(state)
            return {"ok": True, "action": "validated_waiting_for_recurrence", "workspace": workspace["id"], "samples": seen["samples"]}

        seen.pop("validated_workspace", None)
        promote_id = start_action(
            cycle_id=cycle_id,
            domain="code",
            problem_key=f"code:{candidate['fingerprint']}",
            action="promote_validated_patch",
            reason="Dezelfde runtimefout is meermaals waargenomen en de sandboxpatch doorstaat syntax en regressietests.",
            subject=candidate["fingerprint"],
            before={"workspace": workspace["id"], "samples": seen["samples"]},
            reversible=True,
        )
        promotion = _promote(workspace["id"], candidate["fingerprint"])
        state["active"] = {
            "fingerprint": candidate["fingerprint"],
            "workspace_id": workspace["id"],
            "action_id": promote_id,
            "promoted_at": _now().isoformat(),
            "files": promotion["files"],
            "file_backup": promotion["file_backup"],
            "version_backup": promotion["version_backup"],
        }
        _save_state(state)
        return {"ok": True, "action": "promoted_canary", "candidate": candidate["fingerprint"], "promotion": promotion}
    except Exception as exc:
        try:
            complete_action(analysis_id, success=False, result={"error": str(exc)[-2000:]}, effect_score=0.0)
        except Exception:
            pass
        _save_state(state)
        return {"ok": False, "action": "repair_error", "candidate": candidate["fingerprint"], "error": str(exc)[-2000:]}
