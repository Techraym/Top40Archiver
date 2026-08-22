from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timezone

from .db import connect
from .top40 import fetch_chart_from_website


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def editions_with_missing():
    with connect() as con:
        rows = []

        for chart_type, edition_table, entry_table in (
            ("top40", "editions", "chart_entries"),
            ("tipparade", "tipparade_editions", "tipparade_entries"),
        ):
            found = con.execute(
                f"""
                SELECT e.id,e.year,e.week,e.edition_key,
                       COUNT(*) AS missing
                FROM {edition_table} e
                JOIN {entry_table} ce ON ce.edition_id=e.id
                JOIN tracks t ON t.id=ce.track_id
                WHERE
                    t.cover_url IS NULL
                    OR trim(t.cover_url)=''
                    OR t.source_track_id IS NULL
                    OR trim(t.source_track_id)=''
                GROUP BY e.id,e.year,e.week,e.edition_key
                ORDER BY e.year DESC,e.week DESC
                """
            ).fetchall()

            for row in found:
                rows.append(
                    {
                        "chart_type": chart_type,
                        "entry_table": entry_table,
                        "id": int(row["id"]),
                        "year": int(row["year"]),
                        "week": int(row["week"]),
                        "edition_key": str(row["edition_key"]),
                        "missing": int(row["missing"]),
                    }
                )

        rows.sort(
            key=lambda x: (x["year"], x["week"]),
            reverse=True,
        )
        return rows


def process_edition(info) -> tuple[int, int, int]:
    target = date.fromisocalendar(
        info["year"],
        info["week"],
        1,
    )

    chart = fetch_chart_from_website(
        target=target,
        chart_type=info["chart_type"],
        allow_incomplete=True,
    )

    by_position = {
        int(track.position): track
        for track in chart.tracks
    }

    with connect() as con:
        entries = con.execute(
            f"""
            SELECT
                ce.position,
                ce.track_id,
                t.cover_url,
                t.source_track_id
            FROM {info["entry_table"]} ce
            JOIN tracks t ON t.id=ce.track_id
            WHERE ce.edition_id=?
              AND (
                    t.cover_url IS NULL
                    OR trim(t.cover_url)=''
                    OR t.source_track_id IS NULL
                    OR trim(t.source_track_id)=''
                  )
            """,
            (info["id"],),
        ).fetchall()

        cover_updates = 0
        source_updates = 0

        for entry in entries:
            position = int(entry["position"])
            parsed = by_position.get(position)

            if parsed is None:
                continue

            cover_url = str(parsed.cover_url or "").strip() or None
            source_track_id = str(parsed.source_track_id or "").strip() or None

            current_cover = str(entry["cover_url"] or "").strip()
            current_source = str(entry["source_track_id"] or "").strip()

            set_cover = bool(not current_cover and cover_url)
            set_source = bool(not current_source and source_track_id)

            if not set_cover and not set_source:
                continue

            stamp = now_iso()

            con.execute(
                """
                UPDATE tracks
                SET
                    cover_url=CASE
                        WHEN (cover_url IS NULL OR trim(cover_url)='')
                             AND ? IS NOT NULL
                        THEN ?
                        ELSE cover_url
                    END,
                    cover_source=CASE
                        WHEN (cover_url IS NULL OR trim(cover_url)='')
                             AND ? IS NOT NULL
                        THEN 'top40.nl'
                        ELSE cover_source
                    END,
                    cover_checked_at=CASE
                        WHEN (cover_url IS NULL OR trim(cover_url)='')
                             AND ? IS NOT NULL
                        THEN ?
                        ELSE cover_checked_at
                    END,
                    source_track_id=CASE
                        WHEN (source_track_id IS NULL OR trim(source_track_id)='')
                             AND ? IS NOT NULL
                        THEN ?
                        ELSE source_track_id
                    END,
                    updated_at=?
                WHERE id=?
                """,
                (
                    cover_url,
                    cover_url,
                    cover_url,
                    cover_url,
                    stamp,
                    source_track_id,
                    source_track_id,
                    stamp,
                    int(entry["track_id"]),
                ),
            )

            if set_cover:
                cover_updates += 1
            if set_source:
                source_updates += 1

        return cover_updates, source_updates, len(chart.tracks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-editions", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.35)
    args = parser.parse_args()

    editions = editions_with_missing()

    if args.limit_editions > 0:
        editions = editions[:args.limit_editions]

    print(
        f"Top40.nl metadata-backfill: {len(editions)} edities",
        flush=True,
    )

    total_covers = 0
    total_sources = 0
    failures = 0

    for number, info in enumerate(editions, start=1):
        try:
            covers, sources, available = process_edition(info)

            total_covers += covers
            total_sources += sources

            print(
                f"[{number}/{len(editions)}] "
                f"{info['chart_type']} {info['edition_key']} "
                f"- noteringen {available} "
                f"- covers +{covers} "
                f"- source-id +{sources} "
                f"- totaal covers {total_covers} "
                f"- totaal source-id {total_sources}",
                flush=True,
            )

        except Exception as exc:
            failures += 1
            print(
                f"[{number}/{len(editions)}] "
                f"{info['chart_type']} {info['edition_key']} "
                f"- FOUT: {exc}",
                flush=True,
            )

        if args.sleep > 0:
            time.sleep(args.sleep)

    print(
        f"KLAAR: covers={total_covers} "
        f"source_track_ids={total_sources} "
        f"fouten={failures}",
        flush=True,
    )


if __name__ == "__main__":
    main()
