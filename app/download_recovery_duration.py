from __future__ import annotations

import json
from statistics import median
from typing import Any

from .db import connect, now_iso
from .download_db import _cache_key
from .download_matching import (
    MAX_FULL_TRACK_SECONDS_WITHOUT_REFERENCE,
    MIN_FULL_TRACK_SECONDS_WITHOUT_REFERENCE,
    score_candidate,
)

ALGORITHM_VERSION = "candidate_consensus_v1"
EVIDENCE_SOURCE = "candidate_consensus"

EXTRA_VARIANT_MARKERS = [
    "pitch",
    "mashup",
    "mash-up",
    "bootleg",
    "cover",
    "tribute",
    "rework",
    "re-edit",
    "re edit",
    "edit",
    "version",
    "acoustic",
    "demo",
    "session",
    "performance",
    "re-up",
    "garage house",
    "club mix",
]


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _unwanted_marker(
    wanted_title: object,
    candidate_title: object,
) -> bool:
    wanted = _norm(wanted_title)
    found = _norm(candidate_title)

    return any(
        marker in found and marker not in wanted
        for marker in EXTRA_VARIANT_MARKERS
    )


def _source_name(candidate: dict[str, Any]) -> str:
    return _norm(
        candidate.get("channel")
        or candidate.get("uploader")
        or candidate.get("artist")
        or ""
    )


def _dedupe_urls(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for item in items:
        url = str(item["url"])
        old = result.get(url)

        if old is None or float(item["score"]) > float(old["score"]):
            result[url] = item

    return list(result.values())


def _best_cluster(
    items: list[dict[str, Any]],
    tolerance: float = 3.0,
) -> dict[str, Any] | None:
    if not items:
        return None

    possibilities: dict[
        tuple[str, ...],
        dict[str, Any],
    ] = {}

    for seed in items:
        group = [
            item
            for item in items
            if abs(
                float(item["duration"])
                - float(seed["duration"])
            ) <= tolerance
        ]

        group = _dedupe_urls(group)

        if not group:
            continue

        key = tuple(
            sorted(str(item["url"]) for item in group)
        )

        durations = [
            float(item["duration"])
            for item in group
        ]

        sources = {
            str(item["source"])
            for item in group
            if item.get("source")
        }

        possibilities[key] = {
            "duration": round(median(durations), 1),
            "urls": len(group),
            "sources": len(sources),
            "min": round(min(durations), 1),
            "max": round(max(durations), 1),
            "items": group,
        }

    if not possibilities:
        return None

    return sorted(
        possibilities.values(),
        key=lambda cluster: (
            -int(cluster["urls"]),
            -int(cluster["sources"]),
            float(cluster["max"]) - float(cluster["min"]),
        ),
    )[0]


def consensus_for_track(
    track: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Bepaal een conservatieve speelduur uit meerdere cached bronnen.

    De analyse wordt bewust uitgevoerd ZONDER bestaande Spotify- of
    recovery-duur, zodat de consensus zichzelf niet kan bevestigen.
    """
    match_track = dict(track)
    match_track["duration_ms"] = None
    match_track["duration_seconds"] = None

    cache_key = _cache_key(match_track)

    with connect() as con:
        cached = con.execute(
            """
            SELECT
                provider,
                result_url,
                candidate_json,
                match_score
            FROM provider_search_cache
            WHERE cache_key=?
              AND datetime(expires_at)>datetime('now')
            ORDER BY match_score DESC
            """,
            (cache_key,),
        ).fetchall()

    usable: list[dict[str, Any]] = []

    for cache_row in cached:
        try:
            candidate = json.loads(
                cache_row["candidate_json"]
            )
        except Exception:
            continue

        if not isinstance(candidate, dict):
            continue

        url = str(
            candidate.get("url")
            or cache_row["result_url"]
            or ""
        ).strip()

        if not url:
            continue

        try:
            duration = float(
                candidate.get("duration")
                or candidate.get("duration_seconds")
            )
        except (TypeError, ValueError):
            continue

        if not (
            MIN_FULL_TRACK_SECONDS_WITHOUT_REFERENCE
            <= duration
            <= MAX_FULL_TRACK_SECONDS_WITHOUT_REFERENCE
        ):
            continue

        decision = score_candidate(
            match_track,
            candidate,
        )

        if decision.penalties:
            continue

        if float(decision.score) < 96.0:
            continue

        if _unwanted_marker(
            match_track.get("title"),
            candidate.get("title"),
        ):
            continue

        usable.append(
            {
                "url": url,
                "provider": str(cache_row["provider"]),
                "duration": duration,
                "score": float(decision.score),
                "source": _source_name(candidate),
                "title": candidate.get("title"),
            }
        )

    usable = _dedupe_urls(usable)

    best = _best_cluster(usable)

    if best is None:
        return None

    best_urls = {
        str(item["url"])
        for item in best["items"]
    }

    remaining = [
        item
        for item in usable
        if str(item["url"]) not in best_urls
    ]

    second = _best_cluster(remaining)

    basic = (
        int(best["urls"]) >= 3
        and int(best["sources"]) >= 2
        and (
            float(best["max"])
            - float(best["min"])
        ) <= 6.0
    )

    ambiguous = (
        second is not None
        and int(second["urls"]) >= 3
        and int(second["sources"]) >= 2
    )

    strict = basic and not ambiguous

    return {
        "strict": strict,
        "algorithm_version": ALGORITHM_VERSION,
        "source": EVIDENCE_SOURCE,
        "duration_seconds": float(best["duration"]),
        "url_count": int(best["urls"]),
        "source_count": int(best["sources"]),
        "range_min": float(best["min"]),
        "range_max": float(best["max"]),
        "second_url_count": (
            int(second["urls"])
            if second is not None
            else 0
        ),
        "second_duration_seconds": (
            float(second["duration"])
            if second is not None
            else None
        ),
        "best_items": best["items"],
        "second": second,
    }


def save_recovery_duration_evidence(
    track_id: int,
    evidence: dict[str, Any],
) -> None:
    if not evidence.get("strict"):
        raise ValueError(
            "Alleen strikte niet-ambigue consensus mag worden opgeslagen"
        )

    stamp = now_iso()

    payload = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
    )

    with connect() as con:
        con.execute(
            """
            INSERT INTO download_recovery_duration_evidence(
                track_id,
                duration_seconds,
                url_count,
                source_count,
                second_url_count,
                second_duration_seconds,
                algorithm_version,
                source,
                evidence_json,
                created_at,
                updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(track_id) DO UPDATE SET
                duration_seconds=excluded.duration_seconds,
                url_count=excluded.url_count,
                source_count=excluded.source_count,
                second_url_count=excluded.second_url_count,
                second_duration_seconds=excluded.second_duration_seconds,
                algorithm_version=excluded.algorithm_version,
                source=excluded.source,
                evidence_json=excluded.evidence_json,
                updated_at=excluded.updated_at
            """,
            (
                int(track_id),
                float(evidence["duration_seconds"]),
                int(evidence["url_count"]),
                int(evidence["source_count"]),
                int(evidence.get("second_url_count") or 0),
                evidence.get("second_duration_seconds"),
                str(evidence["algorithm_version"]),
                str(evidence["source"]),
                payload,
                stamp,
                stamp,
            ),
        )


def get_recovery_duration_evidence(
    track_id: int,
) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute(
            """
            SELECT
                track_id,
                duration_seconds,
                url_count,
                source_count,
                second_url_count,
                second_duration_seconds,
                algorithm_version,
                source,
                evidence_json,
                created_at,
                updated_at
            FROM download_recovery_duration_evidence
            WHERE track_id=?
            """,
            (int(track_id),),
        ).fetchone()

    return dict(row) if row else None


def allowed_consensus_urls(
    track_id: int,
) -> set[str]:
    """
    Geef uitsluitend de URL's terug uit het opgeslagen,
    strikt goedgekeurde consensuscluster.

    Ontbrekende, corrupte of verouderde evidence resulteert
    fail-closed in een lege set.
    """
    evidence = get_recovery_duration_evidence(int(track_id))

    if not evidence:
        return set()

    if str(evidence.get("source") or "") != EVIDENCE_SOURCE:
        return set()

    if str(evidence.get("algorithm_version") or "") != ALGORITHM_VERSION:
        return set()

    try:
        payload = json.loads(
            str(evidence.get("evidence_json") or "{}")
        )
    except Exception:
        return set()

    if not isinstance(payload, dict):
        return set()

    if payload.get("strict") is not True:
        return set()

    items = payload.get("best_items")

    if not isinstance(items, list):
        return set()

    urls: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        url = str(item.get("url") or "").strip()

        if url:
            urls.add(url)

    return urls
