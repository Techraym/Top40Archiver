from __future__ import annotations

import json
import os
from typing import Any

import requests

from .ai_model_runtime import ModelBusy, model_slot
from .db import connect, now_iso


MODEL_TIMEOUT_SECONDS = 20
MIN_PREVIOUS_FAILURES = 2
MAX_QUERY_LENGTH = 180
NEAR_MATCH_THRESHOLD = 60.0


def _init_state() -> None:
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS download_recovery_ai_state (
                track_id INTEGER PRIMARY KEY
                    REFERENCES tracks(id) ON DELETE CASCADE,
                attempted_at TEXT NOT NULL,
                outcome TEXT NOT NULL,
                suggested_query TEXT,
                confidence REAL
            )
            """
        )


def _recovery_state(track_id: int) -> dict[str, Any] | None:
    _init_state()

    with connect() as con:
        row = con.execute(
            """
            SELECT
                track_id,
                attempted_at,
                outcome,
                suggested_query,
                confidence
            FROM download_recovery_ai_state
            WHERE track_id=?
            """,
            (int(track_id),),
        ).fetchone()

    return dict(row) if row else None


def _record_state(
    track_id: int,
    outcome: str,
    *,
    query: str | None = None,
    confidence: float | None = None,
) -> None:
    _init_state()

    with connect() as con:
        con.execute(
            """
            INSERT INTO download_recovery_ai_state(
                track_id,
                attempted_at,
                outcome,
                suggested_query,
                confidence
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(track_id) DO UPDATE SET
                attempted_at=excluded.attempted_at,
                outcome=excluded.outcome,
                suggested_query=excluded.suggested_query,
                confidence=excluded.confidence
            """,
            (
                int(track_id),
                now_iso(),
                str(outcome),
                query,
                confidence,
            ),
        )


def _compact_rejections(track_id: int) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT
                provider,
                reason,
                match_score
            FROM rejected_candidates
            WHERE track_id=?
            ORDER BY id DESC
            LIMIT 6
            """,
            (int(track_id),),
        ).fetchall()

    return [dict(row) for row in rows]


def _near_match_count(track_id: int) -> int:
    with connect() as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS amount
            FROM rejected_candidates
            WHERE track_id=?
              AND reason IN ('low_match','try_other_provider')
              AND COALESCE(match_score,0) >= ?
            """,
            (
                int(track_id),
                NEAR_MATCH_THRESHOLD,
            ),
        ).fetchone()

    return int(row["amount"] or 0) if row else 0


def _metadata_is_complex(track: dict[str, Any]) -> bool:
    artist = str(track.get("artist") or "").strip()
    title = str(track.get("title") or "").strip()

    lowered = f" {artist.casefold()} "

    markers = (
        " feat",
        " featuring ",
        " ft.",
        " ft ",
        " with ",
        " x ",
        " vs ",
    )

    return (
        len(artist) >= 30
        or len(title) >= 40
        or any(marker in lowered for marker in markers)
        or any(char in artist for char in ("&", "/", "(", '"'))
    )


def _eligible(
    job: dict[str, Any],
    track: dict[str, Any],
) -> dict[str, Any]:
    track_id = int(job["track_id"])
    near_matches = _near_match_count(track_id)
    complex_metadata = _metadata_is_complex(track)

    eligible = complex_metadata or near_matches > 0

    return {
        "eligible": eligible,
        "complex_metadata": complex_metadata,
        "near_matches": near_matches,
    }


def _clean_query(value: object) -> str | None:
    query = " ".join(str(value or "").split()).strip()

    if len(query) < 4 or len(query) > MAX_QUERY_LENGTH:
        return None

    lowered = query.casefold()

    if "http://" in lowered or "https://" in lowered:
        return None

    return query


def _ask_qwen(
    job: dict[str, Any],
    track: dict[str, Any],
) -> dict[str, Any]:

    compact = {
        "artist": track.get("artist"),
        "title": track.get("title"),
        "album": track.get("album"),
        "year": track.get("year"),
        "rejected": _compact_rejections(int(job["track_id"])),
    }

    prompt = (
        "Maak één betere YouTube zoektekst voor exact hetzelfde muzieknummer. "
        "Vereenvoudig artiestcredits, feat/ft/featuring, haakjes en vreemde chart-notatie. "
        "Behoud artiest- en titelidentiteit. "
        "Voeg geen remix, live, cover, karaoke, instrumental, sped-up of slowed toe "
        "tenzij dit expliciet in de titel staat. "
        "Geen URL. Geen uitleg. "
        'Antwoord uitsluitend als JSON: '
        '{"search_query":"artiest titel","confidence":0.90}. '
        + json.dumps(compact, ensure_ascii=False)
    )

    with model_slot(
        "download-recovery-ai",
        priority="background",
        wait_seconds=0.3,
    ):
        response = requests.post(
            os.getenv(
                "OLLAMA_URL",
                "http://127.0.0.1:11434/api/generate",
            ),
            json={
                "model": os.getenv(
                    "TOP40_AI_MODEL",
                    "qwen3:4b",
                ),
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "2h",
                "think": False,
                "options": {
                    "temperature": 0.05,
                    "num_predict": 64,
                },
            },
            timeout=MODEL_TIMEOUT_SECONDS,
        )

    response.raise_for_status()

    raw = str(response.json().get("response") or "{}")
    result = json.loads(raw)

    if not isinstance(result, dict):
        raise ValueError(
            "Qwen recovery-resultaat is geen JSON-object"
        )

    return result


def prepare_recovery_query(
    job: dict[str, Any],
    track: dict[str, Any],
) -> dict[str, Any]:

    if os.getenv("TOP40_DOWNLOAD_RECOVERY_AI", "1") == "0":
        return {
            "prepared": False,
            "action": "disabled",
        }

    track_id = int(job["track_id"])

    existing = str(
        track.get("custom_search_query") or ""
    ).strip()

    if existing:
        return {
            "prepared": False,
            "action": "existing_custom_query",
            "query": existing,
        }

    previous_failures = int(job.get("attempts") or 0)

    if previous_failures < MIN_PREVIOUS_FAILURES:
        return {
            "prepared": False,
            "action": "wait_for_normal_retry",
        }

    eligibility = _eligible(job, track)

    if not eligibility["eligible"]:
        return {
            "prepared": False,
            "action": "not_eligible",
            **eligibility,
        }

    previous = _recovery_state(track_id)

    if previous:
        return {
            "prepared": False,
            "action": "already_attempted",
            "previous_outcome": previous.get("outcome"),
            "previous_query": previous.get("suggested_query"),
            "confidence": previous.get("confidence"),
        }

    try:
        suggestion = _ask_qwen(job, track)

    except ModelBusy as exc:
        # Niet onthouden: later mag opnieuw geprobeerd worden.
        return {
            "prepared": False,
            "action": "model_busy",
            "reason": str(exc),
        }

    except Exception as exc:
        # Ook een tijdelijke Ollama-fout niet permanent onthouden.
        return {
            "prepared": False,
            "action": "model_unavailable",
            "reason": str(exc)[-500:],
        }

    query = _clean_query(
        suggestion.get("search_query")
    )

    try:
        confidence = float(
            suggestion.get("confidence") or 0
        )
    except (TypeError, ValueError):
        confidence = 0.0

    if not query:
        _record_state(
            track_id,
            "no_safe_query",
            confidence=confidence,
        )

        return {
            "prepared": False,
            "action": "no_safe_query",
        }

    if confidence < 0.55:
        _record_state(
            track_id,
            "low_confidence",
            query=query,
            confidence=confidence,
        )

        return {
            "prepared": False,
            "action": "low_confidence",
            "query": query,
            "confidence": confidence,
        }

    normal_query = " ".join(
        [
            str(track.get("artist") or "").strip(),
            str(track.get("title") or "").strip(),
        ]
    ).strip()

    if query.casefold() == normal_query.casefold():
        _record_state(
            track_id,
            "same_query",
            query=query,
            confidence=confidence,
        )

        return {
            "prepared": False,
            "action": "same_query",
            "query": query,
            "confidence": round(confidence, 3),
        }

    with connect() as con:
        updated = con.execute(
            """
            UPDATE tracks
            SET custom_search_query=?,
                updated_at=?
            WHERE id=?
              AND (
                    custom_search_query IS NULL
                    OR trim(custom_search_query)=''
                  )
            """,
            (
                query,
                now_iso(),
                track_id,
            ),
        )

    if not updated.rowcount:
        return {
            "prepared": False,
            "action": "query_already_set",
        }

    _record_state(
        track_id,
        "prepared",
        query=query,
        confidence=confidence,
    )

    return {
        "prepared": True,
        "action": "qwen_search_recovery",
        "query": query,
        "confidence": round(confidence, 3),
        "near_matches": eligibility["near_matches"],
        "complex_metadata": eligibility["complex_metadata"],
        "model": os.getenv(
            "TOP40_AI_MODEL",
            "qwen3:4b",
        ),
    }
