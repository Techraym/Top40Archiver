from __future__ import annotations

import argparse
import hashlib
import io
import mimetypes
from pathlib import Path
from typing import Any

import requests

from .db import connect, now_iso

MAX_IMAGE_BYTES = 4 * 1024 * 1024
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Top40Archiver/1.15.1"})


def init_id3_cover_columns() -> None:
    columns = {
        "cover_embedded_at": "TEXT",
        "cover_embed_status": "TEXT NOT NULL DEFAULT 'pending'",
        "cover_embed_error": "TEXT",
        "cover_content_hash": "TEXT",
    }
    with connect() as con:
        existing = {row["name"] for row in con.execute("PRAGMA table_info(tracks)")}
        for name, definition in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE tracks ADD COLUMN {name} {definition}")


def _download_image(url: str) -> tuple[bytes, str]:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    data = response.content
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"ongeldige afbeeldingsgrootte: {len(data)} bytes")
    mime = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if not mime.startswith("image/"):
        mime = mimetypes.guess_type(url)[0] or "image/jpeg"
    if not mime.startswith("image/"):
        raise ValueError(f"ongeldig content-type: {mime}")
    return data, mime


def _normalize_image(data: bytes, mime: str) -> tuple[bytes, str]:
    try:
        from PIL import Image
    except ImportError:
        return data, mime

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

    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    for key in list(tags.keys()):
        if key.startswith("APIC"):
            del tags[key]
    tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=image_data))
    tags.save(mp3_path, v2_version=3)

    verify = ID3(mp3_path)
    if not any(key.startswith("APIC") for key in verify.keys()):
        raise RuntimeError("APIC-validatie mislukt")

    return {"hash": digest, "bytes": len(image_data), "mime": mime}


def _rows(limit: int) -> list:
    init_id3_cover_columns()
    with connect() as con:
        return con.execute(
            """
            SELECT id,artist,title,mp3_filename,cover_url,cover_content_hash
            FROM tracks
            WHERE download_status='downloaded'
              AND mp3_filename IS NOT NULL
              AND cover_url IS NOT NULL
              AND COALESCE(cover_embed_status,'pending') IN ('pending','retry','failed')
            ORDER BY CASE WHEN cover_embed_status='retry' THEN 0 ELSE 1 END,
                     updated_at DESC,id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()


def process_pending(limit: int = 20) -> dict[str, int]:
    from .db import get_settings

    with connect() as con:
        settings = get_settings(con)
    download_dir = Path(settings.get("download_dir") or "/").expanduser()

    processed = success = failed = 0
    for row in _rows(limit):
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
                        cover_embed_error=NULL,cover_content_hash=?
                    WHERE id=?
                    """,
                    (now_iso(), result["hash"], row["id"]),
                )
            success += 1
            print(f"ID3 COVER OK: {row['artist']} - {row['title']}", flush=True)
        except Exception as exc:
            with connect() as con:
                con.execute(
                    """
                    UPDATE tracks
                    SET cover_embed_status='failed',cover_embed_error=?
                    WHERE id=?
                    """,
                    (str(exc)[-1000:], row["id"]),
                )
            failed += 1
            print(f"ID3 COVER FOUT: {row['artist']} - {row['title']}: {exc}", flush=True)
    return {"processed": processed, "success": success, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(process_pending(args.limit), flush=True)


if __name__ == "__main__":
    main()
