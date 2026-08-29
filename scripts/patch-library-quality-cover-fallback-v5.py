#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

ENGINE = Path('/opt/top40-archiver/app/library_quality.py')
APP = Path('/opt/top40-archiver/app/library_quality_app.py')
OLD_ENGINE_SHA = 'caaedaaecc4f76bff8b32a856b3f8c59b3e93dea31148cd2fa96466fc2432c04'
NEW_ENGINE_SHA = 'af3e6e51b340a7a0828ead6654efe1f51cb5d11c0a436f88ff45c7773c0e2731'
OLD_APP_SHA = 'fff900e85b1e802c63d6ebb4dee39d38ea660b157d3c54c6cf1171f071ddbf92'
NEW_APP_SHA = '9edbfb1dfb6c9359d3847216e0311e807eebd971c73e5a0fa70395a67be36b67'


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

    if s.count('COVER_VERSION = 4') != 1:
        raise SystemExit('FOUT: COVER_VERSION=4 niet uniek gevonden.')
    s = s.replace('COVER_VERSION = 4', 'COVER_VERSION = 5', 1)

    old = 'wanted = ["id", "artist", "title", "genre", "mp3_filename", "spotify_album", "spotify_release_date", "cover_url"]'
    new = 'wanted = ["id", "artist", "title", "genre", "mp3_filename", "spotify_album", "spotify_release_date", "cover_url", "cover_source"]'
    if s.count(old) != 1:
        raise SystemExit('FOUT: track-map anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old = 'for key in ["id", "artist", "title", "genre", "spotify_album", "spotify_release_date", "cover_url"]'
    new = 'for key in ["id", "artist", "title", "genre", "spotify_album", "spotify_release_date", "cover_url", "cover_source"]'
    if s.count(old) != 1:
        raise SystemExit('FOUT: source-signature anker niet uniek gevonden.')
    s = s.replace(old, new, 1)

    old_block = '''            cover_url = str(track.get("cover_url") or "").strip()\n\n            # 1. Hergebruik eerst de gewone Top40Archiver Top40.nl-backfill.\n            #    Die kent de historische hitlijstpositie en is voor ons eigen archief\n            #    de primaire coverbron. MusicBrainz blijft alleen fallback.\n            if not cover_url:\n                found_cover = _top40_backfill_cover(track)\n                cover_url = str(found_cover.get("cover_url") or "").strip()\n                if cover_url:\n                    provenance["cover"] = str(found_cover.get("cover_source") or "top40.nl_backfill")\n\n            # 2. Alleen als Top40.nl niets oplevert: bestaande MusicBrainz/CAA-zoeker.\n            if not cover_url and lookup_cover and track.get("artist") and track.get("title"):\n                try:\n                    found_cover = lookup_cover(str(track["artist"]), str(track["title"])) or {}\n                except Exception:\n                    found_cover = {}\n                cover_url = str(found_cover.get("cover_url") or "").strip()\n                if cover_url:\n                    _save_cover_lookup(track, found_cover)\n                    provenance["cover"] = str(found_cover.get("cover_source") or "cover_art_lookup")\n            if cover_url:\n                cover_download = _download_cover(cover_url)\n                if cover_download:\n                    provenance.setdefault("cover", "top40_cover_url")\n'''
    new_block = '''            tried_cover_urls: set[str] = set()\n            cover_url = str(track.get("cover_url") or "").strip()\n\n            # 1. Een bestaande tracks.cover_url is de goedkoopste bron, maar alleen\n            #    bruikbaar als het beeld nu werkelijk kan worden opgehaald. Een oude\n            #    of verlopen URL mag de verdere coverketen niet blokkeren.\n            if cover_url:\n                tried_cover_urls.add(cover_url)\n                cover_download = _download_cover(cover_url)\n                if cover_download:\n                    provenance["cover"] = str(track.get("cover_source") or "tracks_cover_url")\n\n            # 2. Als er nog geen URL bestond, gebruik eerst de gewone historische\n            #    Top40.nl/Tipparade-backfill. Die vult de centrale tracks-tabel.\n            if not cover_download and not cover_url:\n                found_cover = _top40_backfill_cover(track)\n                candidate_url = str(found_cover.get("cover_url") or "").strip()\n                if candidate_url and candidate_url not in tried_cover_urls:\n                    tried_cover_urls.add(candidate_url)\n                    candidate_download = _download_cover(candidate_url)\n                    if candidate_download:\n                        cover_download = candidate_download\n                        cover_url = candidate_url\n                        provenance["cover"] = str(found_cover.get("cover_source") or "top40.nl_backfill")\n\n            # 3. Als een bestaande/Top40.nl URL niet downloadbaar is, mag die niet\n            #    verhinderen dat de reeds bestaande MusicBrainz/CAA-resolver een\n            #    verse fallback zoekt. Sla een nieuwe URL pas op als de afbeelding\n            #    daadwerkelijk is gedownload en valide genoeg is voor embedding.\n            if not cover_download and lookup_cover and track.get("artist") and track.get("title"):\n                try:\n                    found_cover = lookup_cover(str(track["artist"]), str(track["title"])) or {}\n                except Exception:\n                    found_cover = {}\n                candidate_url = str(found_cover.get("cover_url") or "").strip()\n                if candidate_url and candidate_url not in tried_cover_urls:\n                    tried_cover_urls.add(candidate_url)\n                    candidate_download = _download_cover(candidate_url)\n                    if candidate_download:\n                        cover_download = candidate_download\n                        cover_url = candidate_url\n                        _save_cover_lookup(track, found_cover)\n                        provenance["cover"] = str(found_cover.get("cover_source") or "cover_art_lookup")\n'''
    if s.count(old_block) != 1:
        raise SystemExit('FOUT: v4 coverblok niet uniek gevonden.')
    s = s.replace(old_block, new_block, 1)

    old = '''    cover_retry_count = int(previous["cover_retry_count"] or 0) if previous and "cover_retry_count" in previous.keys() else 0\n    metadata_retry_count = int(previous["metadata_retry_count"] or 0) if previous and "metadata_retry_count" in previous.keys() else 0\n'''
    new = '''    cover_retry_count = int(previous["cover_retry_count"] or 0) if previous and "cover_retry_count" in previous.keys() else 0\n    # Een nieuwe cover-analyzer/bronketen krijgt altijd een verse retrycyclus.\n    # Anders kan een oude unresolved-status uit een vorige versie de nieuwe\n    # resolver direct op retry 2/3 zetten zonder eerlijke nieuwe kans.\n    if previous and int(previous["cover_version"] or 0) < COVER_VERSION:\n        cover_retry_count = 0\n    metadata_retry_count = int(previous["metadata_retry_count"] or 0) if previous and "metadata_retry_count" in previous.keys() else 0\n'''
    if s.count(old) != 1:
        raise SystemExit('FOUT: cover retry-anker niet uniek gevonden.')
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
    if s.count('1.16.23.3') != 2:
        raise SystemExit('FOUT: verwachte 1.16.23.3 versieankers niet gevonden.')
    s = s.replace('1.16.23.3', '1.16.23.4')
    atomic_write(APP, s)
    result = sha(APP)
    if result != NEW_APP_SHA:
        raise SystemExit(f'FOUT: gepatchte app SHA klopt niet: {result}')


if __name__ == '__main__':
    patch_engine()
    patch_app()
    print('Library Quality 1.16.23.4 stale-cover fallback toegevoegd.')
