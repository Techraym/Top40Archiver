from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import APP_DIR, DATA_DIR

ROOT = DATA_DIR / "ai" / "development"
WORKSPACES = ROOT / "workspaces"
REPORTS = ROOT / "reports"
QUARANTINE = DATA_DIR / "ai" / "quarantine"
ALLOWED_SUFFIXES = {".py", ".sh", ".html", ".css", ".js", ".json", ".md", ".toml", ".ini", ".yml", ".yaml", ".txt"}
BLOCKED_PARTS = {".git", "venv", "__pycache__", "downloads", "backups", "secrets"}
MAX_PATCH_BYTES = 512_000
MAX_FILES = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9-]{12,64}", value):
        raise ValueError("ongeldig workspace-id")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _workspace(workspace_id: str) -> Path:
    return WORKSPACES / _safe_id(workspace_id)


def _allowed_relative(path: str) -> Path:
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("pad valt buiten repository")
    if any(part in BLOCKED_PARTS for part in rel.parts):
        raise ValueError("pad is geblokkeerd")
    if rel.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("bestandstype is niet toegestaan")
    return rel


def create_workspace(title: str, problem: str) -> dict[str, Any]:
    workspace_id = uuid.uuid4().hex
    base = _workspace(workspace_id)
    source = base / "source"
    source.mkdir(parents=True, exist_ok=False)

    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in BLOCKED_PARTS or name.endswith((".sqlite", ".sqlite3", ".mp3", ".zip"))}

    shutil.copytree(APP_DIR, source, dirs_exist_ok=True, ignore=ignore)
    metadata = {
        "id": workspace_id,
        "title": str(title).strip()[:160],
        "problem": str(problem).strip()[:5000],
        "created_at": _now(),
        "status": "analysis",
        "production_write": False,
        "source": str(APP_DIR),
        "workspace": str(source),
        "policy": "sandbox-only",
    }
    _write_json(base / "workspace.json", metadata)
    return metadata


def list_source_files(workspace_id: str, query: str = "") -> list[dict[str, Any]]:
    source = _workspace(workspace_id) / "source"
    needle = query.casefold().strip()
    result: list[dict[str, Any]] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        rel = path.relative_to(source).as_posix()
        if needle and needle not in rel.casefold():
            try:
                if needle not in path.read_text(encoding="utf-8", errors="ignore").casefold():
                    continue
            except OSError:
                continue
        result.append({"path": rel, "bytes": path.stat().st_size})
        if len(result) >= 500:
            break
    return result


def read_source_file(workspace_id: str, path: str) -> dict[str, Any]:
    rel = _allowed_relative(path)
    target = _workspace(workspace_id) / "source" / rel
    if not target.is_file():
        raise FileNotFoundError(path)
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": rel.as_posix(), "content": content[:200_000], "truncated": len(content) > 200_000}


def save_patch(workspace_id: str, patch: str, reason: str) -> dict[str, Any]:
    raw = patch.encode("utf-8")
    if len(raw) > MAX_PATCH_BYTES:
        raise ValueError("patch is te groot")
    if "diff --git" not in patch or "--- " not in patch or "+++ " not in patch:
        raise ValueError("alleen unified git-diffs zijn toegestaan")
    if any(marker in patch for marker in ("/.git/", "../", "requirements.lock")):
        raise ValueError("patch bevat een geblokkeerd pad")
    touched = sorted(set(re.findall(r"^\+\+\+ b/(.+)$", patch, flags=re.M)))
    if not touched or len(touched) > MAX_FILES:
        raise ValueError("ongeldig aantal gewijzigde bestanden")
    for item in touched:
        _allowed_relative(item)
    base = _workspace(workspace_id)
    patch_path = base / "proposal.patch"
    patch_path.write_text(patch, encoding="utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    proposal = {"workspace_id": workspace_id, "reason": reason[:3000], "sha256": digest, "files": touched, "saved_at": _now(), "status": "proposed"}
    _write_json(base / "proposal.json", proposal)
    return proposal


def _run(command: list[str], cwd: Path, timeout: int = 180) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    return {"command": command, "ok": completed.returncode == 0, "returncode": completed.returncode, "stdout": completed.stdout[-20_000:], "stderr": completed.stderr[-20_000:]}


def validate_workspace(workspace_id: str) -> dict[str, Any]:
    base = _workspace(workspace_id)
    source = base / "source"
    patch_path = base / "proposal.patch"
    if not patch_path.exists():
        raise FileNotFoundError("proposal.patch ontbreekt")

    check = _run(["git", "apply", "--check", str(patch_path)], source)
    apply_result = {"ok": False, "skipped": True}
    syntax = {"ok": False, "skipped": True}
    tests = {"ok": False, "skipped": True}
    if check["ok"]:
        apply_result = _run(["git", "apply", str(patch_path)], source)
    if apply_result.get("ok"):
        python_files = [str(path) for path in source.rglob("*.py") if "venv" not in path.parts]
        syntax = _run([str(APP_DIR / "venv/bin/python"), "-m", "py_compile", *python_files], source, timeout=240) if python_files else {"ok": True, "skipped": True}
        if syntax["ok"]:
            tests = _run([str(APP_DIR / "venv/bin/python"), "-m", "pytest", "-q"], source, timeout=600)

    ok = bool(check["ok"] and apply_result.get("ok") and syntax.get("ok") and tests.get("ok"))
    report = {
        "workspace_id": workspace_id,
        "validated_at": _now(),
        "ok": ok,
        "status": "ready_for_review" if ok else "validation_failed",
        "git_apply_check": check,
        "apply": apply_result,
        "syntax": syntax,
        "tests": tests,
        "production_changed": False,
    }
    _write_json(base / "validation.json", report)
    _write_json(REPORTS / f"{workspace_id}.json", report)
    metadata_path = base / "workspace.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = report["status"]
    metadata["updated_at"] = _now()
    _write_json(metadata_path, metadata)
    return report


def workspace_status(workspace_id: str) -> dict[str, Any]:
    base = _workspace(workspace_id)
    result: dict[str, Any] = {}
    for name in ("workspace", "proposal", "validation", "pr-plan"):
        path = base / f"{name}.json"
        if path.exists():
            result[name.replace("-", "_")] = json.loads(path.read_text(encoding="utf-8"))
    return result


def list_workspaces(limit: int = 50) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not WORKSPACES.exists():
        return items
    for path in sorted(WORKSPACES.glob("*/workspace.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items


def create_pr_plan(workspace_id: str, title: str, body: str) -> dict[str, Any]:
    status = workspace_status(workspace_id)
    validation = status.get("validation", {})
    proposal = status.get("proposal", {})
    if not validation.get("ok"):
        raise ValueError("alleen gevalideerde patches mogen naar review")
    plan = {
        "workspace_id": workspace_id,
        "title": title[:160],
        "body": body[:10_000],
        "branch": f"ai/{workspace_id[:12]}",
        "base": "main",
        "patch_sha256": proposal.get("sha256"),
        "created_at": _now(),
        "status": "awaiting_human_approval",
        "automatic_push_enabled": os.getenv("TOP40_AI_GITHUB_WRITE", "0") == "1",
    }
    _write_json(_workspace(workspace_id) / "pr-plan.json", plan)
    return plan


def quarantine_workspace(workspace_id: str, reason: str) -> dict[str, Any]:
    base = _workspace(workspace_id)
    destination = QUARANTINE / f"development-{workspace_id}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(base), str(destination))
    metadata = {"workspace_id": workspace_id, "original_path": str(base), "quarantine_path": str(destination), "reason": reason[:2000], "quarantined_at": _now(), "restore_id": uuid.uuid4().hex}
    _write_json(destination / "quarantine.json", metadata)
    return metadata
