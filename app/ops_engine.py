from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

from .db import connect, get_settings, now_iso, set_settings

OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT NOT NULL,
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  diagnosis TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  severity TEXT NOT NULL DEFAULT 'warning',
  status TEXT NOT NULL DEFAULT 'open',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  recommended_action TEXT,
  occurrences INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  resolved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_open_fingerprint
ON incidents(fingerprint) WHERE status='open';

CREATE TABLE IF NOT EXISTS repair_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  action_name TEXT NOT NULL,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'started',
  result_message TEXT,
  verification_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_repair_attempts_incident ON repair_attempts(incident_id,id DESC);
"""

PATTERNS = (
    ("youtube_rate_limit", "YouTube beperkt tijdelijk de downloads", 0.96, "critical", "pause_downloads", re.compile(r"\b(429|too many requests|sign in to confirm|not a bot|captcha)\b", re.I)),
    ("youtube_forbidden", "YouTube weigert de download", 0.88, "error", "pause_downloads", re.compile(r"\b(403|forbidden|request blocked)\b", re.I)),
    ("youtube_missing", "Bronvideo is verdwenen of niet beschikbaar", 0.90, "warning", "clear_source_and_retry", re.compile(r"\b(video unavailable|private video|removed by the uploader|not available in your country|copyright)\b", re.I)),
    ("extractor_outdated", "Downloadercomponenten lijken verouderd", 0.88, "error", "manual_update_required", re.compile(r"\b(nsig|signature extraction|player response|ejs|javascript runtime)\b", re.I)),
    ("ffmpeg_failure", "Audioconversie met FFmpeg is mislukt", 0.92, "error", "retry_track", re.compile(r"\b(ffmpeg|postprocessing|requested format is not available|conversion failed)\b", re.I)),
    ("storage_failure", "Opslaglocatie is niet beschikbaar of niet schrijfbaar", 0.95, "critical", "pause_downloads", re.compile(r"\b(read-only file system|permission denied|no space left|usb.*not|niet schrijfbaar|input/output error)\b", re.I)),
    ("database_locked", "Database is tijdelijk vergrendeld", 0.92, "warning", "retry_later", re.compile(r"database is locked|database table is locked", re.I)),
    ("network_timeout", "Netwerkverbinding of downloadbron reageert te langzaam", 0.78, "warning", "retry_later", re.compile(r"\b(timeout|timed out|temporary failure|connection reset|network is unreachable)\b", re.I)),
)


def init_ops() -> None:
    with connect() as con:
        con.executescript(OPS_SCHEMA)


def _fingerprint(category: str, message: str) -> str:
    normalized = re.sub(r"\d+", "#", message.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()[:800]
    return hashlib.sha256(f"{category}|{normalized}".encode("utf-8")).hexdigest()[:32]


def diagnose(message: str) -> dict[str, Any]:
    text = str(message or "").strip()
    for category, title, confidence, severity, action, pattern in PATTERNS:
        if pattern.search(text):
            return {
                "category": category,
                "title": title,
                "confidence": confidence,
                "severity": severity,
                "recommended_action": action,
                "diagnosis": _diagnosis_text(category),
            }
    return {
        "category": "unknown",
        "title": "Onbekende technische fout",
        "confidence": 0.45,
        "severity": "warning",
        "recommended_action": "manual_review",
        "diagnosis": "De fout is nog niet betrouwbaar aan een bekend patroon gekoppeld. Bekijk de ruwe logregels voordat een herstelactie wordt uitgevoerd.",
    }


def _diagnosis_text(category: str) -> str:
    return {
        "youtube_rate_limit": "Er zijn signalen van een tijdelijke YouTube-rate-limit of botcontrole. Nieuwe downloads moeten worden gestopt om verdere blokkering te voorkomen.",
        "youtube_forbidden": "YouTube weigert één of meer aanvragen. Dit kan een tijdelijke beperking, verouderde extractor of afgeschermde bron zijn.",
        "youtube_missing": "De opgeslagen of gevonden bronvideo is verwijderd, privé, regionaal geblokkeerd of anderszins niet meer bruikbaar.",
        "extractor_outdated": "De huidige yt-dlp-, Deno- of EJS-combinatie kan de actuele YouTube-player niet correct verwerken.",
        "ffmpeg_failure": "De bron is gevonden, maar de audioselectie of conversie naar MP3 is mislukt.",
        "storage_failure": "Doorgaan kan bestanden beschadigen of verloren downloads veroorzaken. De wachtrij moet gepauzeerd blijven totdat de opslag weer gezond is.",
        "database_locked": "Een ander proces hield de SQLite-database tijdelijk bezet. Een korte back-off is meestal voldoende.",
        "network_timeout": "De verbinding was tijdelijk te traag of onderbroken. Een vertraagde retry is veiliger dan direct meerdere nieuwe workers starten.",
    }.get(category, "Onbekend probleem.")


def scan_failed_tracks(limit: int = 200) -> dict[str, int]:
    init_ops()
    cutoff = (datetime.now().astimezone() - timedelta(days=7)).isoformat(timespec="seconds")
    with connect() as con:
        rows = con.execute(
            """
            SELECT id,artist,title,error_message,updated_at
            FROM tracks
            WHERE download_status='failed' AND error_message IS NOT NULL AND updated_at>=?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()

        created = updated = 0
        for row in rows:
            message = str(row["error_message"] or "")
            result = diagnose(message)
            fingerprint = _fingerprint(result["category"], message)
            evidence = [{
                "track_id": row["id"],
                "artist": row["artist"],
                "title": row["title"],
                "message": message[-1800:],
                "seen_at": row["updated_at"],
            }]
            existing = con.execute(
                "SELECT id,evidence_json FROM incidents WHERE fingerprint=? AND status='open'",
                (fingerprint,),
            ).fetchone()
            if existing:
                stored = json.loads(existing["evidence_json"] or "[]")
                known_ids = {item.get("track_id") for item in stored}
                if row["id"] not in known_ids:
                    stored = (stored + evidence)[-20:]
                con.execute(
                    "UPDATE incidents SET occurrences=occurrences+1,last_seen=?,evidence_json=? WHERE id=?",
                    (row["updated_at"], json.dumps(stored, ensure_ascii=False), existing["id"]),
                )
                updated += 1
            else:
                con.execute(
                    """
                    INSERT INTO incidents(
                      fingerprint,category,title,diagnosis,confidence,severity,status,
                      evidence_json,recommended_action,first_seen,last_seen
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fingerprint, result["category"], result["title"], result["diagnosis"],
                        result["confidence"], result["severity"], "open",
                        json.dumps(evidence, ensure_ascii=False), result["recommended_action"],
                        row["updated_at"], row["updated_at"],
                    ),
                )
                created += 1
    return {"created": created, "updated": updated, "scanned": len(rows)}


def list_incidents(limit: int = 100) -> list[dict[str, Any]]:
    init_ops()
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM incidents ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
            attempts = con.execute(
                "SELECT * FROM repair_attempts WHERE incident_id=? ORDER BY id DESC LIMIT 10",
                (row["id"],),
            ).fetchall()
            item["repairs"] = [dict(x) for x in attempts]
            result.append(item)
        return result


def execute_repair(incident_id: int, action_name: str | None = None) -> dict[str, Any]:
    init_ops()
    with connect() as con:
        incident = con.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if not incident:
            raise ValueError("Incident niet gevonden")
        action = action_name or incident["recommended_action"] or "manual_review"
        started = now_iso()
        cursor = con.execute(
            "INSERT INTO repair_attempts(incident_id,action_name,status,started_at) VALUES(?,?,?,?)",
            (incident_id, action, "started", started),
        )
        attempt_id = cursor.lastrowid

    status = "completed"
    verification: dict[str, Any] = {}
    message = ""
    try:
        if action == "pause_downloads":
            set_settings({"operations_download_paused": "1", "download_workers": "1"})
            with connect() as con:
                con.execute("UPDATE tracks SET download_status='pending',updated_at=? WHERE download_status='downloading'", (now_iso(),))
            verification = {"paused": True, "workers": 1}
            message = "Downloadwachtrij gepauzeerd en workerlimiet veilig op 1 gezet."
        elif action == "clear_source_and_retry":
            with connect() as con:
                evidence = json.loads(incident["evidence_json"] or "[]")
                track_ids = sorted({int(x["track_id"]) for x in evidence if x.get("track_id")})
                for track_id in track_ids:
                    con.execute(
                        "UPDATE tracks SET youtube_url=NULL,download_status='pending',download_attempts=0,error_message=NULL,updated_at=? WHERE id=?",
                        (now_iso(), track_id),
                    )
            verification = {"queued_tracks": track_ids}
            message = f"Oude bron verwijderd en {len(track_ids)} nummer(s) opnieuw in de wachtrij gezet."
        elif action in {"retry_track", "retry_later"}:
            with connect() as con:
                evidence = json.loads(incident["evidence_json"] or "[]")
                track_ids = sorted({int(x["track_id"]) for x in evidence if x.get("track_id")})
                for track_id in track_ids:
                    con.execute("UPDATE tracks SET download_status='pending',error_message=NULL,updated_at=? WHERE id=?", (now_iso(), track_id))
            verification = {"queued_tracks": track_ids, "downloads_paused": get_settings().get("operations_download_paused", "0") == "1"}
            message = f"{len(track_ids)} nummer(s) voorbereid voor een gecontroleerde retry."
        else:
            status = "requires_approval"
            message = "Deze actie vereist handmatige beoordeling en is niet automatisch uitgevoerd."
    except Exception as exc:
        status = "failed"
        message = str(exc)[-2000:]

    with connect() as con:
        con.execute(
            "UPDATE repair_attempts SET status=?,result_message=?,verification_json=?,finished_at=? WHERE id=?",
            (status, message, json.dumps(verification, ensure_ascii=False), now_iso(), attempt_id),
        )
        if status == "completed":
            con.execute("UPDATE incidents SET status='resolved',resolved_at=? WHERE id=?", (now_iso(), incident_id))
    return {"attempt_id": attempt_id, "status": status, "message": message, "verification": verification}


def resume_downloads() -> dict[str, Any]:
    set_settings({"operations_download_paused": "0"})
    return {"paused": False, "message": "Downloadwachtrij vrijgegeven. Start eerst bij voorkeur één testdownload."}
