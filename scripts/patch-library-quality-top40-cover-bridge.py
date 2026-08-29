#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

ENGINE = Path('/opt/top40-archiver/app/library_quality.py')
APP = Path('/opt/top40-archiver/app/library_quality_app.py')
OLD_ENGINE_SHA = '29445213ef090e293540c2c62b9c02149c001aa543563191cf83ea952eacc5e1'
NEW_ENGINE_SHA = 'caaedaaecc4f76bff8b32a856b3f8c59b3e93dea31148cd2fa96466fc2432c04'
OLD_APP_SHA = '07b95a2f83d9129f6c47e8d32d9662a1c29126933269472c2bd57f137d1b5f18'
NEW_APP_SHA = 'fff900e85b1e802c63d6ebb4dee39d38ea660b157d3c54c6cf1171f071ddbf92'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
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

    old = '''try:\n    from .cover_art import lookup_cover\nexcept Exception:  # pragma: no cover - keep scanner usable when cover service is unavailable\n    lookup_cover = None\n'''
    new = '''try:\n    from .cover_art import lookup_cover\nexcept Exception:  # pragma: no cover - keep scanner usable when cover service is unavailable\n    lookup_cover = None\n\ntry:\n    from .top40_cover_backfill import process_edition as top40_process_edition\nexcept Exception:  # pragma: no cover - old installs remain usable without the backfill module\n    top40_process_edition = None\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: import-anker voor Top40 cover bridge niet uniek gevonden.')
    s = s.replace(old, new, 1)

    if s.count('COVER_VERSION = 3') != 1:
        raise SystemExit('FOUT: COVER_VERSION=3 niet uniek gevonden.')
    s = s.replace('COVER_VERSION = 3', 'COVER_VERSION = 4', 1)

    anchor = 'def _save_cover_lookup(track: dict[str, Any], result: dict[str, str]) -> None:\n'
    if s.count(anchor) != 1:
        raise SystemExit('FOUT: _save_cover_lookup anker niet uniek gevonden.')
    helper = '''_TOP40_BACKFILL_EDITION_CACHE: set[tuple[str, int]] = set()\n\n\ndef _top40_backfill_cover(track: dict[str, Any]) -> dict[str, str]:\n    \"\"\"Gebruik de bestaande Top40.nl backfill voor een track voordat MusicBrainz wordt geprobeerd.\n\n    De gewone Top40Archiver-backfill haalt cover_url uit historische Top40/Tipparade-edities.\n    Library Quality hergebruikt die bron en matcher; het bouwt hier dus geen tweede\n    Top40.nl-coverzoeker. Per run wordt een editie maximaal één keer opgehaald.\n    \"\"\"\n    if top40_process_edition is None:\n        return {}\n    try:\n        track_id = int(track.get(\"id\") or 0)\n    except (TypeError, ValueError):\n        return {}\n    if track_id <= 0:\n        return {}\n\n    candidates: list[dict[str, Any]] = []\n    try:\n        with connect() as con:\n            for chart_type, edition_table, entry_table in (\n                (\"top40\", \"editions\", \"chart_entries\"),\n                (\"tipparade\", \"tipparade_editions\", \"tipparade_entries\"),\n            ):\n                rows = con.execute(\n                    f\"\"\"\n                    SELECT e.id,e.year,e.week,e.edition_key\n                    FROM {edition_table} e\n                    JOIN {entry_table} ce ON ce.edition_id=e.id\n                    WHERE ce.track_id=?\n                    ORDER BY e.year DESC,e.week DESC\n                    LIMIT 4\n                    \"\"\",\n                    (track_id,),\n                ).fetchall()\n                for row in rows:\n                    candidates.append({\n                        \"chart_type\": chart_type,\n                        \"entry_table\": entry_table,\n                        \"id\": int(row[\"id\"]),\n                        \"year\": int(row[\"year\"]),\n                        \"week\": int(row[\"week\"]),\n                        \"edition_key\": str(row[\"edition_key\"]),\n                    })\n    except Exception:\n        return {}\n\n    candidates.sort(key=lambda item: (item[\"year\"], item[\"week\"]), reverse=True)\n\n    for info in candidates[:6]:\n        cache_key = (str(info[\"chart_type\"]), int(info[\"id\"]))\n        if cache_key not in _TOP40_BACKFILL_EDITION_CACHE:\n            try:\n                top40_process_edition(info)\n            except Exception:\n                _TOP40_BACKFILL_EDITION_CACHE.add(cache_key)\n                continue\n            _TOP40_BACKFILL_EDITION_CACHE.add(cache_key)\n\n        try:\n            with connect() as con:\n                row = con.execute(\n                    \"SELECT cover_url,cover_source FROM tracks WHERE id=?\",\n                    (track_id,),\n                ).fetchone()\n        except Exception:\n            row = None\n\n        cover_url = str(row[\"cover_url\"] or \"\").strip() if row else \"\"\n        if cover_url:\n            cover_source = str(row[\"cover_source\"] or \"top40.nl\").strip() if row else \"top40.nl\"\n            track[\"cover_url\"] = cover_url\n            return {\"cover_url\": cover_url, \"cover_source\": cover_source or \"top40.nl\"}\n\n    return {}\n\n\n'''
    s = s.replace(anchor, helper + anchor, 1)

    old_block = '''            cover_url = str(track.get("cover_url") or "").strip()\n            if not cover_url and lookup_cover and track.get("artist") and track.get("title"):\n                try:\n                    found_cover = lookup_cover(str(track["artist"]), str(track["title"])) or {}\n                except Exception:\n                    found_cover = {}\n                cover_url = str(found_cover.get("cover_url") or "").strip()\n                if cover_url:\n                    _save_cover_lookup(track, found_cover)\n                    provenance["cover"] = str(found_cover.get("cover_source") or "cover_art_lookup")\n'''
    new_block = '''            cover_url = str(track.get("cover_url") or "").strip()\n\n            # 1. Hergebruik eerst de gewone Top40Archiver Top40.nl-backfill.\n            #    Die kent de historische hitlijstpositie en is voor ons eigen archief\n            #    de primaire coverbron. MusicBrainz blijft alleen fallback.\n            if not cover_url:\n                found_cover = _top40_backfill_cover(track)\n                cover_url = str(found_cover.get("cover_url") or "").strip()\n                if cover_url:\n                    provenance["cover"] = str(found_cover.get("cover_source") or "top40.nl_backfill")\n\n            # 2. Alleen als Top40.nl niets oplevert: bestaande MusicBrainz/CAA-zoeker.\n            if not cover_url and lookup_cover and track.get("artist") and track.get("title"):\n                try:\n                    found_cover = lookup_cover(str(track["artist"]), str(track["title"])) or {}\n                except Exception:\n                    found_cover = {}\n                cover_url = str(found_cover.get("cover_url") or "").strip()\n                if cover_url:\n                    _save_cover_lookup(track, found_cover)\n                    provenance["cover"] = str(found_cover.get("cover_source") or "cover_art_lookup")\n'''
    if s.count(old_block) != 1:
        raise SystemExit('FOUT: cover-resolve blok niet uniek gevonden.')
    s = s.replace(old_block, new_block, 1)

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
    if s.count('1.16.23.2') != 2:
        raise SystemExit('FOUT: verwachte 1.16.23.2 versieankers niet gevonden.')
    s = s.replace('1.16.23.2', '1.16.23.3')
    atomic_write(APP, s)
    result = sha(APP)
    if result != NEW_APP_SHA:
        raise SystemExit(f'FOUT: gepatchte app SHA klopt niet: {result}')


if __name__ == '__main__':
    patch_engine()
    patch_app()
    print('Library Quality 1.16.23.3 Top40 cover bridge toegevoegd.')
