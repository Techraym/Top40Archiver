#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

ENGINE = Path('/opt/top40-archiver/app/library_quality.py')
APP = Path('/opt/top40-archiver/app/library_quality_app.py')
OLD_ENGINE_SHA = 'af3e6e51b340a7a0828ead6654efe1f51cb5d11c0a436f88ff45c7773c0e2731'
NEW_ENGINE_SHA = '7bc676ae70b2d5c884ee6d8c99cdad21294229102051061525ba3458d9677d89'
OLD_APP_SHA = '9edbfb1dfb6c9359d3847216e0311e807eebd971c73e5a0fa70395a67be36b67'
NEW_APP_SHA = '48786827e42d56da194e8f5df446375aa17ef5e92a4f1f32d3a410f1445382a9'


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

    if s.count('COVER_VERSION = 5') != 1:
        raise SystemExit('FOUT: COVER_VERSION=5 niet uniek gevonden.')
    s = s.replace('COVER_VERSION = 5', 'COVER_VERSION = 6', 1)

    old = '''DEFAULT_COVER_LIMIT = int(os.getenv("TOP40_LIBRARY_COVER_LIMIT", "25"))\n'''
    new = '''DEFAULT_COVER_LIMIT = int(os.getenv("TOP40_LIBRARY_COVER_LIMIT", "25"))\n\n# Coververrijking mag nooit de bibliotheekscan minutenlang blokkeren.\n# De totale online coverketen per track is standaard maximaal 12 seconden.\nCOVER_TRACK_BUDGET = float(os.getenv("TOP40_LIBRARY_COVER_TRACK_BUDGET", "12"))\nCOVER_HTTP_CONNECT_TIMEOUT = float(os.getenv("TOP40_LIBRARY_COVER_CONNECT_TIMEOUT", "2"))\nCOVER_HTTP_READ_TIMEOUT = float(os.getenv("TOP40_LIBRARY_COVER_READ_TIMEOUT", "4"))\nCOVER_LOOKUP_TIMEOUT = float(os.getenv("TOP40_LIBRARY_COVER_LOOKUP_TIMEOUT", "7"))\nTOP40_BACKFILL_TIMEOUT = float(os.getenv("TOP40_LIBRARY_TOP40_BACKFILL_TIMEOUT", "6"))\nTOP40_BACKFILL_MAX_EDITIONS = max(1, int(os.getenv("TOP40_LIBRARY_TOP40_BACKFILL_MAX_EDITIONS", "1")))\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: cover-config anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''def _download_cover(url: str) -> tuple[bytes, str] | None:\n    try:\n        response = requests.get(url, timeout=30, headers={"User-Agent": "Top40Archiver LibraryQuality/1.16.23"})\n        response.raise_for_status()\n        if not response.content or len(response.content) > 6 * 1024 * 1024:\n            return None\n        mime = (response.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip()\n        if not mime.startswith("image/"):\n            mime = "image/jpeg"\n        return response.content, mime\n    except Exception:\n        return None\n'''
    new = '''_COVER_DOWNLOAD_FAILURE_CACHE: set[str] = set()\n_COVER_LOOKUP_CACHE: dict[tuple[str, str], dict[str, str]] = {}\n_LAST_COVER_LOOKUP_STARTED = 0.0\n\n\ndef _cover_remaining(deadline: float | None) -> float:\n    if deadline is None:\n        return COVER_TRACK_BUDGET\n    return max(0.0, deadline - time.monotonic())\n\n\ndef _download_cover(url: str, deadline: float | None = None) -> tuple[bytes, str] | None:\n    url = str(url or "").strip()\n    if not url or url in _COVER_DOWNLOAD_FAILURE_CACHE:\n        return None\n    remaining = _cover_remaining(deadline)\n    if remaining < 0.75:\n        return None\n    connect_timeout = max(0.5, min(COVER_HTTP_CONNECT_TIMEOUT, remaining / 2.0))\n    read_timeout = max(0.5, min(COVER_HTTP_READ_TIMEOUT, max(0.5, remaining - connect_timeout)))\n    try:\n        response = requests.get(\n            url,\n            timeout=(connect_timeout, read_timeout),\n            headers={"User-Agent": "Top40Archiver LibraryQuality/1.16.23.5"},\n        )\n        response.raise_for_status()\n        if not response.content or len(response.content) > 6 * 1024 * 1024:\n            _COVER_DOWNLOAD_FAILURE_CACHE.add(url)\n            return None\n        mime = (response.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip()\n        if not mime.startswith("image/"):\n            mime = "image/jpeg"\n        return response.content, mime\n    except Exception:\n        _COVER_DOWNLOAD_FAILURE_CACHE.add(url)\n        return None\n\n\ndef _lookup_cover_bounded(artist: str, title: str, deadline: float | None = None) -> dict[str, str]:\n    \"\"\"Draai de bestaande MusicBrainz/CAA-resolver geïsoleerd met een harde timeout.\n\n    cover_art.lookup_cover behoudt zijn normale retrygedrag voor de gewone coverworker.\n    Alleen Library Quality begrenst die resolver, zodat een slechte externe bron de\n    bibliotheekscan niet meer 1-2 minuten per track kan vasthouden.\n    \"\"\"\n    global _LAST_COVER_LOOKUP_STARTED\n    if lookup_cover is None:\n        return {}\n    key = (" ".join(str(artist or "").casefold().split()), " ".join(str(title or "").casefold().split()))\n    if key in _COVER_LOOKUP_CACHE:\n        return dict(_COVER_LOOKUP_CACHE[key])\n    remaining = _cover_remaining(deadline)\n    if remaining < 0.75:\n        return {}\n\n    # MusicBrainz vraagt beleefde request-pacing. Ook losse helperprocessen worden\n    # daarom vanuit de scanner minimaal ~1 seconde uit elkaar gestart.\n    wait = 1.05 - (time.monotonic() - _LAST_COVER_LOOKUP_STARTED)\n    if wait > 0:\n        time.sleep(min(wait, max(0.0, _cover_remaining(deadline) - 0.75)))\n    remaining = _cover_remaining(deadline)\n    if remaining < 0.75:\n        return {}\n\n    timeout = max(0.75, min(COVER_LOOKUP_TIMEOUT, remaining))\n    app_root = str(Path(__file__).resolve().parent.parent)\n    env = os.environ.copy()\n    env["PYTHONPATH"] = app_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")\n    code = (\n        "import json,sys; "\n        "from app.cover_art import lookup_cover; "\n        "print(json.dumps(lookup_cover(sys.argv[1], sys.argv[2]) or {}))"\n    )\n    _LAST_COVER_LOOKUP_STARTED = time.monotonic()\n    try:\n        proc = subprocess.run(\n            [os.sys.executable, "-c", code, str(artist), str(title)],\n            text=True,\n            capture_output=True,\n            timeout=timeout,\n            env=env,\n        )\n        if proc.returncode != 0:\n            result: dict[str, str] = {}\n        else:\n            payload = json.loads((proc.stdout or "{}").strip().splitlines()[-1])\n            result = {str(k): str(v) for k, v in payload.items() if v not in (None, "")} if isinstance(payload, dict) else {}\n    except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError, OSError):\n        result = {}\n    _COVER_LOOKUP_CACHE[key] = dict(result)\n    return result\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: _download_cover anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '_TOP40_BACKFILL_EDITION_CACHE: set[tuple[str, int]] = set()\n\n\ndef _top40_backfill_cover'
    new = '_TOP40_BACKFILL_EDITION_CACHE: set[tuple[str, int]] = set()\n_ACTIVE_COVER_DEADLINE: float | None = None\n\n\ndef _top40_backfill_cover'
    if s.count(old) != 1:
        raise SystemExit('FOUT: Top40 backfill cache-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''    for info in candidates[:6]:\n        cache_key = (str(info["chart_type"]), int(info["id"]))\n        if cache_key not in _TOP40_BACKFILL_EDITION_CACHE:\n            try:\n                top40_process_edition(info)\n            except Exception:\n                _TOP40_BACKFILL_EDITION_CACHE.add(cache_key)\n                continue\n            _TOP40_BACKFILL_EDITION_CACHE.add(cache_key)\n'''
    new = '''    for info in candidates[:TOP40_BACKFILL_MAX_EDITIONS]:\n        cache_key = (str(info["chart_type"]), int(info["id"]))\n        if cache_key not in _TOP40_BACKFILL_EDITION_CACHE:\n            # process_edition wordt in een apart proces uitgevoerd. Daardoor kan een\n            # trage/onbereikbare Top40.nl-pagina hard worden afgebroken zonder de\n            # 8085-worker te laten hangen. De gewone backfillmodule blijft ongewijzigd.\n            app_root = str(Path(__file__).resolve().parent.parent)\n            env = os.environ.copy()\n            env["PYTHONPATH"] = app_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")\n            code = (\n                "import json,sys; "\n                "from app.top40_cover_backfill import process_edition; "\n                "process_edition(json.loads(sys.argv[1])); print('OK')"\n            )\n            timeout = max(0.75, min(TOP40_BACKFILL_TIMEOUT, _cover_remaining(_ACTIVE_COVER_DEADLINE)))\n            try:\n                if _cover_remaining(_ACTIVE_COVER_DEADLINE) < 0.75:\n                    return {}\n                subprocess.run(\n                    [os.sys.executable, "-c", code, json.dumps(info)],\n                    text=True,\n                    capture_output=True,\n                    timeout=timeout,\n                    env=env,\n                    check=False,\n                )\n            except (subprocess.TimeoutExpired, OSError):\n                pass\n            _TOP40_BACKFILL_EDITION_CACHE.add(cache_key)\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: Top40 backfill loop-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''        if budget.take_cover():\n            cover_attempted = True\n            tried_cover_urls: set[str] = set()\n            cover_url = str(track.get("cover_url") or "").strip()\n'''
    new = '''        if budget.take_cover():\n            cover_attempted = True\n            global _ACTIVE_COVER_DEADLINE\n            cover_deadline = time.monotonic() + max(2.0, COVER_TRACK_BUDGET)\n            _ACTIVE_COVER_DEADLINE = cover_deadline\n            tried_cover_urls: set[str] = set()\n            cover_url = str(track.get("cover_url") or "").strip()\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: cover deadline-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    if s.count('cover_download = _download_cover(cover_url)') != 1:
        raise SystemExit('FOUT: bestaande cover download-anker niet gevonden.')
    s = s.replace('cover_download = _download_cover(cover_url)', 'cover_download = _download_cover(cover_url, cover_deadline)', 1)
    if s.count('candidate_download = _download_cover(candidate_url)') != 2:
        raise SystemExit('FOUT: kandidaat cover download-ankers niet gevonden.')
    s = s.replace('candidate_download = _download_cover(candidate_url)', 'candidate_download = _download_cover(candidate_url, cover_deadline)')

    old = '''                try:\n                    found_cover = lookup_cover(str(track["artist"]), str(track["title"])) or {}\n                except Exception:\n                    found_cover = {}\n'''
    new = '''                found_cover = _lookup_cover_bounded(\n                    str(track["artist"]),\n                    str(track["title"]),\n                    cover_deadline,\n                )\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: MusicBrainz lookup-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''                        provenance["cover"] = str(found_cover.get("cover_source") or "cover_art_lookup")\n        else:\n            cover_deferred = True\n'''
    new = '''                        provenance["cover"] = str(found_cover.get("cover_source") or "cover_art_lookup")\n            _ACTIVE_COVER_DEADLINE = None\n        else:\n            cover_deferred = True\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: cover deadline-reset anker niet uniek gevonden.')
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
    if s.count('1.16.23.4') != 2:
        raise SystemExit('FOUT: verwachte 1.16.23.4 versieankers niet gevonden.')
    s = s.replace('1.16.23.4', '1.16.23.5')

    old = '''    RADIO_WRITE_CONFIDENCE,\n    current_state,\n'''
    new = '''    RADIO_WRITE_CONFIDENCE,\n    COVER_TRACK_BUDGET,\n    COVER_LOOKUP_TIMEOUT,\n    TOP40_BACKFILL_TIMEOUT,\n    current_state,\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: app import-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = '''        "radio_write_confidence": RADIO_WRITE_CONFIDENCE,\n'''
    new = '''        "radio_write_confidence": RADIO_WRITE_CONFIDENCE,\n        "cover_track_budget": COVER_TRACK_BUDGET,\n        "cover_lookup_timeout": COVER_LOOKUP_TIMEOUT,\n        "top40_backfill_timeout": TOP40_BACKFILL_TIMEOUT,\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: health timeout-anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    atomic_write(APP, s)
    result = sha(APP)
    if result != NEW_APP_SHA:
        raise SystemExit(f'FOUT: gepatchte app SHA klopt niet: {result}')


if __name__ == '__main__':
    patch_engine()
    patch_app()
    print('Library Quality 1.16.23.5 cover-performance fix toegevoegd.')
