from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .db import connect, now_iso
from .cover_validation import is_placeholder_url

MAX_IMAGE_BYTES = 4 * 1024 * 1024
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Top40Archiver/1.15.1"})


def init_id3_cover_columns() -> None:
    columns = {
        "cover_embedded_at": "TEXT",
        "cover_embed_status": "TEXT NOT NULL DEFAULT 'pending'",
        "cover_embed_error": "TEXT",
        "cover_content_hash": "TEXT",
        "cover_embed_attempted_at": "TEXT",
        "cover_embed_retry_at": "TEXT",
        "cover_embedded_url": "TEXT",
    }
    with connect() as con:
        existing = {row["name"] for row in con.execute("PRAGMA table_info(tracks)")}
        for name, definition in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE tracks ADD COLUMN {name} {definition}")


def _download_image(url: str) -> tuple[bytes, str]:
    if is_placeholder_url(url):
        raise ValueError("Standaardafbeelding geweigerd")
    with SESSION.get(url, timeout=(10, 20), stream=True) as response:
        response.raise_for_status()
        if is_placeholder_url(response.url):
            raise ValueError("Omleiding naar standaardafbeelding geweigerd")
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("Afbeelding groter dan 4 MiB")
        if not data:
            raise ValueError("Lege afbeelding")
        # PIL determines the actual format; Content-Type is not proof of an image.
        return bytes(data), str(response.headers.get("Content-Type") or "")


def _normalize_image(data: bytes, mime: str) -> tuple[bytes, str]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Python-pakket Pillow ontbreekt; afbeelding niet geschreven") from exc

    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((1000, 1000))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue(), "image/jpeg"


def embed_cover(mp3_path: Path, cover_url: str) -> dict[str, Any]:
    try:
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError
    except ImportError as exc:
        raise RuntimeError("Python-pakket mutagen ontbreekt") from exc

    if not mp3_path.is_file():
        raise FileNotFoundError(str(mp3_path))

    image_data, mime = _download_image(cover_url)
    image_data, mime = _normalize_image(image_data, mime)
    digest = hashlib.sha256(image_data).hexdigest()

    # Do not modify the original until the complete new ID3 tag has been verified.
    original = mp3_path.stat()
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if mp3_path.is_symlink() or original.st_nlink != 1:
        raise RuntimeError("Symlink of hardlink: bestand niet automatisch vervangen")
    fd, name = tempfile.mkstemp(prefix=".top40-cover-", suffix=".tmp", dir=mp3_path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(mp3_path, temporary)
        try:
            tags = ID3(temporary)
        except ID3NoHeaderError:
            tags = ID3()
        for key in list(tags.keys()):
            if key.startswith("APIC") and int(tags[key].type) in (0, 3):
                del tags[key]
        # Keep back covers and other explicitly typed artwork.
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Top40 Front", data=image_data))
        tags.save(temporary, v2_version=3)
        verify = ID3(temporary)
        if not any(int(frame.type) == 3 and frame.mime == mime
                   and hashlib.sha256(frame.data).hexdigest() == digest
                   for frame in verify.getall("APIC")):
            raise RuntimeError("APIC-inhoudsvalidatie mislukt")
        if signature(mp3_path.stat()) != signature(original):
            raise RuntimeError("MP3 intussen gewijzigd; later opnieuw proberen")
        current = temporary.stat()
        if (current.st_uid, current.st_gid) != (original.st_uid, original.st_gid):
            os.chown(temporary, original.st_uid, original.st_gid)
        os.chmod(temporary, original.st_mode & 0o777)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, mp3_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"hash": digest, "bytes": len(image_data), "mime": mime}


def requeue_placeholders() -> int:
    """Invalidate URL metadata; existing artwork is replaced only after a real match."""
    init_id3_cover_columns()
    count = 0
    with connect() as con:
        rows = con.execute("SELECT id,cover_url FROM tracks WHERE cover_url IS NOT NULL").fetchall()
        for row in rows:
            if not is_placeholder_url(row["cover_url"]):
                continue
            con.execute(
                """UPDATE tracks SET cover_url=NULL,cover_source=NULL,cover_checked_at=NULL,
                   cover_embed_status='pending',cover_embed_retry_at=NULL,
                   cover_embed_error='Standaardafbeelding: nieuwe hoes zoeken'
                   WHERE id=? AND cover_url=?""", (row["id"], row["cover_url"]))
            count += 1
    if count:
        print(f"ID3 COVER: {count} standaardafbeeldingen opnieuw in zoekwachtrij", flush=True)
    return count


def _rows(limit: int) -> list:
    init_id3_cover_columns()
    with connect() as con:
        return con.execute(
            """
            SELECT id,artist,title,mp3_filename,cover_url,cover_content_hash
            FROM tracks
            WHERE download_status='downloaded'
              AND mp3_filename IS NOT NULL
              AND cover_url IS NOT NULL AND TRIM(cover_url)<>''
              AND (cover_embed_retry_at IS NULL OR julianday(cover_embed_retry_at)<=julianday('now'))
              AND (COALESCE(cover_embed_status,'pending') IN ('pending','retry','failed')
                   OR (cover_embedded_url IS NOT NULL AND cover_embedded_url<>cover_url))
            ORDER BY COALESCE(cover_embed_attempted_at,''), updated_at DESC,id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()


def process_pending(limit: int = 200, deadline: float | None = None) -> dict[str, int]:
    from .db import get_settings

    with connect() as con:
        settings = get_settings(con)
    download_dir = Path(settings.get("download_dir") or "/").expanduser()

    processed = success = failed = 0
    for row in _rows(limit):
        if deadline is not None and time.monotonic() >= deadline:
            break
        processed += 1
        path = Path(str(row["mp3_filename"]))
        if not path.is_absolute():
            path = download_dir / path
        try:
            result = embed_cover(path, str(row["cover_url"]))
            with connect() as con:
                con.execute(
                    """
                    UPDATE tracks
                    SET cover_embedded_at=?,cover_embed_status='embedded',
                        cover_embed_error=NULL,cover_content_hash=?,cover_embedded_url=?,
                        cover_embed_attempted_at=?,cover_embed_retry_at=NULL
                    WHERE id=? AND cover_url=?
                    """,
                    (now_iso(), result["hash"], row["cover_url"], now_iso(), row["id"], row["cover_url"]),
                )
            success += 1
            print(f"ID3 COVER OK: {row['artist']} - {row['title']}", flush=True)
        except Exception as exc:
            with connect() as con:
                con.execute(
                    """
                    UPDATE tracks
                    SET cover_embed_status='failed',cover_embed_error=?,
                        cover_embed_attempted_at=?,cover_embed_retry_at=?
                    WHERE id=? AND cover_url=?
                    """,
                    (str(exc)[-1000:], now_iso(),
                     (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                     row["id"], row["cover_url"]),
                )
            failed += 1
            print(f"ID3 COVER FOUT: {row['artist']} - {row['title']}: {exc}", flush=True)
    return {"processed": processed, "success": success, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--max-seconds", type=int, default=240)
    args = parser.parse_args()
    requeue_placeholders()
    deadline = time.monotonic() + max(1, min(args.max_seconds, 1200))
    total = {"processed": 0, "success": 0, "failed": 0}
    while time.monotonic() < deadline:
        result = process_pending(args.limit, deadline=deadline)
        for key in total:
            total[key] += result[key]
        print(result, flush=True)
        if not args.drain or not result["processed"]:
            break
    print({"total": total}, flush=True)
    if total["failed"] and not total["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
