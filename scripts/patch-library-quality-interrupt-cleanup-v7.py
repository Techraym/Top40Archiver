#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

ENGINE = Path('/opt/top40-archiver/app/library_quality.py')
APP = Path('/opt/top40-archiver/app/library_quality_app.py')
OLD_ENGINE_SHA = '7bc676ae70b2d5c884ee6d8c99cdad21294229102051061525ba3458d9677d89'
NEW_ENGINE_SHA = 'e79648de1af1f99483a1c1cf22e0f9751d0e83a2f7ffae58ea2072110408b892'
OLD_APP_SHA = '48786827e42d56da194e8f5df446375aa17ef5e92a4f1f32d3a410f1445382a9'
NEW_APP_SHA = 'e62ba4910b457ff7f0cbbc06aaa4a64053e8caef44480907220e36789ad2cb83'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, path.stat().st_mode)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def patch_engine() -> None:
    current = sha(ENGINE)
    if current == NEW_ENGINE_SHA:
        return
    if current != OLD_ENGINE_SHA:
        raise SystemExit(f'FOUT: onverwachte library_quality.py SHA: {current}')

    s = ENGINE.read_text(encoding='utf-8')

    old = 'import re\nimport shutil\n'
    new = 'import re\nimport shutil\nimport signal\n'
    if s.count(old) != 1:
        raise SystemExit('FOUT: signal import-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''def current_state() -> dict[str, Any]:\n    try:\n        return json.loads(STATE_PATH.read_text(encoding="utf-8"))\n    except Exception:\n        return {"running": False}\n\n\ndef scan_library'''
    new = '''def current_state() -> dict[str, Any]:\n    try:\n        return json.loads(STATE_PATH.read_text(encoding="utf-8"))\n    except Exception:\n        return {"running": False}\n\n\ndef _mark_run_interrupted(run_id: int, trigger: str, total: int, counts: dict[str, int]) -> dict[str, Any]:\n    \"\"\"Sluit een door SIGINT/SIGTERM afgebroken scan atomair af.\"\"\"\n    finished = now_iso()\n    previous_state = current_state()\n    with connect() as con:\n        con.execute(\n            \"\"\"\n            UPDATE library_quality_runs\n            SET status='interrupted',finished_at=?,processed=?,skipped=?,repaired=?,failed=?,current_file=NULL\n            WHERE id=? AND status='running'\n            \"\"\",\n            (finished, counts["processed"], counts["skipped"], counts["repaired"], counts["failed"], run_id),\n        )\n    result = {\n        "ok": False,\n        "running": False,\n        "interrupted": True,\n        "run_id": run_id,\n        "trigger": trigger,\n        "total": total,\n        **counts,\n        "current": previous_state.get("current"),\n        "current_file": None,\n        "started_at": previous_state.get("started_at"),\n        "finished_at": finished,\n    }\n    _write_state(result)\n    return result\n\n\ndef scan_library'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: interrupted-helper anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''    lock_file = LOCK_PATH.open("a+")\n    try:\n'''
    new = '''    lock_file = LOCK_PATH.open("a+")\n    run_id: int | None = None\n    files: list[Path] = []\n    counts = {"processed": 0, "skipped": 0, "repaired": 0, "failed": 0}\n    try:\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: scan run-context anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''        counts = {"processed": 0, "skipped": 0, "repaired": 0, "failed": 0}\n        _write_state({"running": True, "run_id": run_id, "trigger": trigger, "total": len(files), **counts, "current_file": None, "started_at": now_iso()})\n'''
    new = '''        _write_state({"running": True, "run_id": run_id, "trigger": trigger, "total": len(files), **counts, "current_file": None, "started_at": now_iso()})\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: counts verplaats-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''        _write_state(result)\n        return result\n    finally:\n'''
    new = '''        _write_state(result)\n        return result\n    except KeyboardInterrupt:\n        if run_id is not None:\n            with contextlib.suppress(Exception):\n                _mark_run_interrupted(run_id, trigger, len(files), counts)\n        raise\n    finally:\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: scan interrupt-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = 'def main() -> None:\n'
    new = '''def _interrupt_signal_handler(signum: int, frame: Any) -> None:\n    raise KeyboardInterrupt\n\n\ndef main() -> None:\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: CLI signal-handler anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''    elif args.cmd == "scan":\n        print(json.dumps(scan_library(args.trigger, args.force, args.heavy_limit, args.enrich_limit, args.cover_limit, args.max_files), ensure_ascii=False, indent=2))\n'''
    new = '''    elif args.cmd == "scan":\n        previous_term_handler = signal.signal(signal.SIGTERM, _interrupt_signal_handler)\n        try:\n            result = scan_library(args.trigger, args.force, args.heavy_limit, args.enrich_limit, args.cover_limit, args.max_files)\n            print(json.dumps(result, ensure_ascii=False, indent=2))\n        except KeyboardInterrupt:\n            print("\\nBibliotheekcontrole onderbroken; status veilig opgeslagen.", flush=True)\n            raise SystemExit(130)\n        finally:\n            signal.signal(signal.SIGTERM, previous_term_handler)\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: CLI scan-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    atomic_write(ENGINE, s)
    result = sha(ENGINE)
    if result != NEW_ENGINE_SHA:
        raise SystemExit(f'FOUT: gepatchte engine SHA klopt niet: {result}')


def patch_app() -> None:
    current = sha(APP)
    if current == NEW_APP_SHA:
        return
    if current != OLD_APP_SHA:
        raise SystemExit(f'FOUT: onverwachte library_quality_app.py SHA: {current}')
    s = APP.read_text(encoding='utf-8')
    if s.count('1.16.23.5') != 2:
        raise SystemExit('FOUT: verwachte 1.16.23.5 versieankers niet gevonden.')
    s = s.replace('1.16.23.5', '1.16.23.6')
    atomic_write(APP, s)
    result = sha(APP)
    if result != NEW_APP_SHA:
        raise SystemExit(f'FOUT: gepatchte app SHA klopt niet: {result}')


if __name__ == '__main__':
    patch_engine()
    patch_app()
    print('Library Quality 1.16.23.6 interrupt-cleanup toegevoegd.')
