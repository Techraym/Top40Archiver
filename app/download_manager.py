from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

from .ai_session_console import scope_held
from .config import DATA_DIR
from .db import connect, now_iso
from .download_db import (
    cache_candidate,
    cached_candidates,
    claim_jobs,
    enqueue_pending_tracks,
    init_download_db,
    job_cancel_requested,
    mark_provider_request,
    provider_configs,
    record_provider_attempt,
    reject_candidate,
    rejected_urls,
    set_job_state,
    update_provider_runtime,
)
from .download_matching import MatchDecision, score_candidate
from .metadata import UNKNOWN_GENRE, clean_genre, resolve_genre, track_relative_path
from .providers import provider_from_row
from .providers.base import AudioProvider, ProviderCandidate, ProviderError

MAX_GLOBAL_DOWNLOADS = 4
MAX_PARALLEL_PROVIDER_SEARCHES = 3
PRIMARY_PRIORITY_CUTOFF = 80
MIN_FILE_BYTES = 32 * 1024
RETRY_BACKOFF_SECONDS = (30, 120, 600, 1800, 7200)
MANAGER_LOCK = DATA_DIR / "download-manager.lock"
STATE_FILE = DATA_DIR / "download_state.json"


class DownloadValidationError(RuntimeError):
    pass


class _ProviderRuntime:
    def __init__(self, row: dict[str, Any]):
        self.name = str(row["provider"])
        self.max_concurrent = max(1, int(row.get("max_concurrent") or 1))
        self.requests_per_minute = max(1, int(row.get("requests_per_minute") or 1))
        self.min_delay_seconds = max(0.0, float(row.get("min_delay_seconds") or 0))
        self.semaphore = threading.BoundedSemaphore(self.max_concurrent)
        self.lock = threading.Lock()
        self.last_request_monotonic = 0.0

    def acquire(self):
        return self.semaphore

    def pace(self) -> None:
        with self.lock:
            minimum = max(self.min_delay_seconds, 60.0 / self.requests_per_minute)
            remaining = minimum - (time.monotonic() - self.last_request_monotonic)
            if remaining > 0:
                time.sleep(remaining)
            self.last_request_monotonic = time.monotonic()
            mark_provider_request(self.name)


_RUNTIME_LOCK = threading.Lock()
_RUNTIMES: dict[str, _ProviderRuntime] = {}


def _runtime(row: dict[str, Any]) -> _ProviderRuntime:
    name = str(row["provider"])
    with _RUNTIME_LOCK:
        current = _RUNTIMES.get(name)
        expected = (
            max(1, int(row.get("max_concurrent") or 1)),
            max(1, int(row.get("requests_per_minute") or 1)),
            max(0.0, float(row.get("min_delay_seconds") or 0)),
        )
        if current is None or (
            current.max_concurrent,
            current.requests_per_minute,
            current.min_delay_seconds,
        ) != expected:
            current = _ProviderRuntime(row)
            _RUNTIMES[name] = current
        return current


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _provider_available(row: dict[str, Any]) -> bool:
    if not bool(int(row.get("enabled", 0))):
        return False
    cooldown = _parse_time(row.get("cooldown_until"))
    if cooldown and cooldown > _utcnow():
        return False
    return str(row.get("status") or "healthy") != "offline"


def _candidate_from_dict(provider: str, value: dict[str, Any]) -> ProviderCandidate | None:
    try:
        url = str(value.get("url") or "").strip()
        title = str(value.get("title") or "").strip()
        if not url.startswith("http") or not title:
            return None
        return ProviderCandidate(
            provider=provider,
            url=url,
            title=title,
            artist=value.get("artist"),
            duration=value.get("duration"),
            album=value.get("album"),
            year=value.get("year"),
            isrc=value.get("isrc"),
            source_id=value.get("source_id"),
            uploader=value.get("uploader"),
            channel=value.get("channel"),
            description=value.get("description"),
            metadata=value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
        )
    except Exception:
        return None


def _track_context(job: dict[str, Any]) -> dict[str, Any]:
    year = None
    release = str(job.get("spotify_release_date") or "")
    if len(release) >= 4 and release[:4].isdigit():
        year = int(release[:4])
    return {
        "track_id": int(job["track_id"]),
        "artist": str(job.get("spotify_artist") or job.get("artist") or "").strip(),
        "title": str(job.get("spotify_title") or job.get("title") or "").strip(),
        "album": str(job.get("spotify_album") or "").strip() or None,
        "duration_ms": int(job["spotify_duration_ms"]) if job.get("spotify_duration_ms") else None,
        "isrc": str(job.get("spotify_isrc") or "").strip() or None,
        "year": year,
        "custom_search_query": str(job.get("custom_search_query") or "").strip() or None,
    }


def _search_provider(
    row: dict[str, Any],
    track: dict[str, Any],
) -> dict[str, Any]:
    provider_name = str(row["provider"])
    provider = provider_from_row(row)
    runtime = _runtime(row)
    rejected = rejected_urls(int(track["track_id"]), provider_name)
    started = time.monotonic()
    candidates: list[ProviderCandidate] = []
    cache_hits = 0

    for cached in cached_candidates(track, provider_name, limit=4):
        candidate = _candidate_from_dict(provider_name, cached)
        if candidate and candidate.url not in rejected:
            candidates.append(candidate)
            cache_hits += 1

    network_error: ProviderError | None = None
    try:
        with runtime.acquire():
            runtime.pace()
            found = provider.search(track, limit=6)
        known = {candidate.url for candidate in candidates}
        for candidate in found:
            if candidate.url not in rejected and candidate.url not in known:
                candidates.append(candidate)
                known.add(candidate.url)
    except ProviderError as exc:
        network_error = exc
        update_provider_runtime(
            provider_name,
            success=False,
            error_category=exc.category,
            base_backoff_seconds=int(row.get("error_backoff_seconds") or 120),
        )

    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = score_candidate(track, candidate.as_match_dict())
        cache_candidate(track, provider_name, candidate.url, asdict(candidate), decision.score)
        if not decision.accepted:
            reject_candidate(
                int(track["track_id"]),
                provider_name,
                candidate.url,
                decision.reason,
                decision.score,
                {
                    "duration_difference": decision.duration_difference,
                    "penalties": decision.penalties,
                    "components": decision.components,
                },
            )
            continue
        scored.append({"candidate": candidate, "decision": decision})

    elapsed = int((time.monotonic() - started) * 1000)
    scored.sort(key=lambda item: float(item["decision"].score), reverse=True)
    return {
        "provider": provider_name,
        "provider_row": row,
        "provider_object": provider,
        "search_ms": elapsed,
        "cache_hits": cache_hits,
        "accepted": scored,
        "error": network_error,
    }


def _search_group(rows: list[dict[str, Any]], track: dict[str, Any]) -> list[dict[str, Any]]:
    if not rows:
        return []
    workers = min(MAX_PARALLEL_PROVIDER_SEARCHES, len(rows))
    results: list[dict[str, Any]] = []
    if workers == 1:
        return [_search_provider(rows[0], track)]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="provider-search") as executor:
        futures = [executor.submit(_search_provider, row, track) for row in rows]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"provider": "unknown", "accepted": [], "error": exc, "search_ms": None})
    return results


def _ffprobe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name,bit_rate:stream=index,codec_type,codec_name,sample_rate,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise DownloadValidationError((completed.stderr or "FFprobe kon bronbestand niet lezen")[-2000:])
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DownloadValidationError("FFprobe gaf geen geldige JSON terug") from exc
    streams = [item for item in payload.get("streams", []) if item.get("codec_type") == "audio"]
    if not streams:
        raise DownloadValidationError("Bronbestand bevat geen audiostream")
    audio = streams[0]
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    try:
        duration = float(fmt.get("duration")) if fmt.get("duration") else None
    except (TypeError, ValueError):
        duration = None
    return {
        "duration": duration,
        "codec": str(audio.get("codec_name") or "") or None,
        "bitrate": int(audio.get("bit_rate") or fmt.get("bit_rate") or 0) or None,
        "sample_rate": int(audio.get("sample_rate") or 0) or None,
        "format_name": str(fmt.get("format_name") or "") or None,
    }


def _validate_download(path: Path, track: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size < MIN_FILE_BYTES:
        raise DownloadValidationError("Bronbestand ontbreekt of is te klein")
    prefix = path.read_bytes()[:2048].lstrip().casefold()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        raise DownloadValidationError("Download bevat HTML in plaats van audio")
    info = _ffprobe(path)
    expected_ms = track.get("duration_ms")
    if expected_ms and info.get("duration"):
        difference = abs(float(info["duration"]) - float(expected_ms) / 1000.0)
        if difference > 15:
            raise DownloadValidationError(f"Gedownloade audio wijkt {difference:.1f}s af van verwachte speelduur")
        info["duration_difference"] = round(difference, 2)
    return info


def _convert_to_mp3(source: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "320k",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size < MIN_FILE_BYTES:
        output.unlink(missing_ok=True)
        raise DownloadValidationError((completed.stderr or "FFmpeg-conversie mislukt")[-2000:])
    info = _ffprobe(output)
    if info.get("codec") != "mp3":
        output.unlink(missing_ok=True)
        raise DownloadValidationError("Uitvoerbestand is geen geldige MP3")
    return info


def _silence_guard(path: Path, duration: float | None) -> None:
    if not duration or duration < 20:
        return
    completed = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-50dB:d=8",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    text = completed.stderr or ""
    silent = 0.0
    for line in text.splitlines():
        if "silence_duration:" not in line:
            continue
        try:
            silent = max(silent, float(line.rsplit("silence_duration:", 1)[1].strip().split()[0]))
        except (TypeError, ValueError, IndexError):
            continue
    if silent >= max(20.0, float(duration) * 0.8):
        raise DownloadValidationError("Audiobestand is vrijwel volledig stil")


def _final_path(job: dict[str, Any], track: dict[str, Any]) -> tuple[str, Path, str]:
    with connect() as con:
        settings = {row["key"]: row["value"] for row in con.execute("SELECT key,value FROM settings")}
    current_genre = clean_genre(job.get("genre")) if job.get("genre") else UNKNOWN_GENRE
    genre = current_genre if current_genre != UNKNOWN_GENRE else resolve_genre(str(job["artist"]), str(job["title"]))
    relative = track_relative_path(genre, str(job["artist"]), str(job["title"]))
    base = Path(settings["download_dir"]).expanduser()
    return genre, base / relative, relative.as_posix()


def _copy_atomic(source: Path, destination: Path) -> None:
    # Bestaande audio is data, geen tijdelijke download. De manager mag die nooit
    # vervangen, ook niet wanneer SQLite door een eerdere storing achterloopt.
    if destination.exists():
        raise DownloadValidationError(
            f"existing_target_conflict: bestaande audio wordt niet overschreven: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if temporary.stat().st_size < MIN_FILE_BYTES:
            raise DownloadValidationError("MP3-uitvoer is te klein")
        # os.link creëert het doel alleen als het nog niet bestaat. Daardoor is ook
        # een race tussen de exists-check en deze stap non-destructief.
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise DownloadValidationError(
                f"existing_target_conflict: bestaande audio wordt niet overschreven: {destination}"
            ) from exc
        temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _try_candidate(
    job: dict[str, Any],
    track: dict[str, Any],
    search_result: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    provider_name = str(search_result["provider"])
    provider: AudioProvider = search_result["provider_object"]
    row = search_result["provider_row"]
    candidate: ProviderCandidate = item["candidate"]
    decision: MatchDecision = item["decision"]
    started_at = now_iso()
    download_started = time.monotonic()
    runtime = _runtime(row)

    set_job_state(
        int(job["id"]),
        "downloading",
        preferred_provider=provider_name,
    )
    if job_cancel_requested(int(job["id"])):
        raise DownloadValidationError("job_cancelled")

    with tempfile.TemporaryDirectory(prefix=f"provider-{provider_name}-", dir=DATA_DIR / "download-temp") as td:
        temp = Path(td)
        try:
            with runtime.acquire():
                runtime.pace()
                source = provider.download(candidate, temp, timeout=600)
            download_ms = int((time.monotonic() - download_started) * 1000)
            set_job_state(int(job["id"]), "validating", preferred_provider=provider_name)
            source_info = _validate_download(source, track)
            _silence_guard(source, source_info.get("duration"))

            set_job_state(int(job["id"]), "processing", preferred_provider=provider_name)
            converted = temp / "output.mp3"
            output_info = _convert_to_mp3(source, converted)
            _silence_guard(converted, output_info.get("duration"))
            genre, final, relative = _final_path(job, track)
            _copy_atomic(converted, final)

            with connect() as con:
                con.execute(
                    """
                    UPDATE tracks SET
                      download_status='downloaded',genre=?,mp3_filename=?,error_message=NULL,
                      processed_at=?,updated_at=?,
                      youtube_url=CASE WHEN ? IN ('youtube','youtube_music') THEN ? ELSE youtube_url END,
                      youtube_match_score=CASE WHEN ? IN ('youtube','youtube_music') THEN ?/100.0 ELSE youtube_match_score END,
                      youtube_duration_seconds=CASE WHEN ? IN ('youtube','youtube_music') THEN ? ELSE youtube_duration_seconds END
                    WHERE id=?
                    """,
                    (
                        genre,
                        relative,
                        now_iso(),
                        now_iso(),
                        provider_name,
                        candidate.url,
                        provider_name,
                        decision.score,
                        provider_name,
                        candidate.duration,
                        int(job["track_id"]),
                    ),
                )

            record_provider_attempt(
                job_id=int(job["id"]),
                track_id=int(job["track_id"]),
                provider=provider_name,
                candidate_url=candidate.url,
                match_score=decision.score,
                search_ms=search_result.get("search_ms"),
                download_ms=download_ms,
                success=True,
                source_codec=source_info.get("codec"),
                source_bitrate=source_info.get("bitrate"),
                source_sample_rate=source_info.get("sample_rate"),
                output_codec=output_info.get("codec"),
                output_bitrate=output_info.get("bitrate"),
                started_at=started_at,
            )
            update_provider_runtime(provider_name, success=True)
            set_job_state(int(job["id"]), "completed", preferred_provider=provider_name)
            return {
                "ok": True,
                "track_id": int(job["track_id"]),
                "provider": provider_name,
                "match_score": decision.score,
                "filename": relative,
                "source_quality": source_info,
                "output_quality": output_info,
            }
        except ProviderError as exc:
            update_provider_runtime(
                provider_name,
                success=False,
                error_category=exc.category,
                base_backoff_seconds=int(row.get("error_backoff_seconds") or 120),
            )
            record_provider_attempt(
                job_id=int(job["id"]),
                track_id=int(job["track_id"]),
                provider=provider_name,
                candidate_url=candidate.url,
                match_score=decision.score,
                search_ms=search_result.get("search_ms"),
                download_ms=int((time.monotonic() - download_started) * 1000),
                success=False,
                error_category=exc.category,
                error=str(exc),
                started_at=started_at,
            )
            reject_candidate(int(job["track_id"]), provider_name, candidate.url, exc.category, decision.score)
            raise
        except DownloadValidationError as exc:
            if str(exc).startswith("existing_target_conflict:"):
                category = "existing_target_conflict"
            else:
                category = "invalid_audio" if str(exc) != "job_cancelled" else "cancelled"
            record_provider_attempt(
                job_id=int(job["id"]),
                track_id=int(job["track_id"]),
                provider=provider_name,
                candidate_url=candidate.url,
                match_score=decision.score,
                search_ms=search_result.get("search_ms"),
                download_ms=int((time.monotonic() - download_started) * 1000),
                success=False,
                error_category=category,
                error=str(exc),
                started_at=started_at,
            )
            # Een padconflict zegt niets over de provider/kandidaat; bewaar de
            # kandidaat dus niet als fout. De bestaande audio blijft onaangeraakt.
            if category not in {"cancelled", "existing_target_conflict"}:
                reject_candidate(int(job["track_id"]), provider_name, candidate.url, category, decision.score)
            raise


def _provider_groups() -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]]]:
    rows = [row for row in provider_configs(enabled_only=True) if _provider_available(row)]
    primary = [row for row in rows if int(row.get("effective_priority", int(row["priority"]) + int(row.get("ai_priority_adjustment") or 0))) < PRIMARY_PRIORITY_CUTOFF]
    fallback = [row for row in rows if row not in primary]
    primary_groups = [primary[index : index + MAX_PARALLEL_PROVIDER_SEARCHES] for index in range(0, len(primary), MAX_PARALLEL_PROVIDER_SEARCHES)]
    fallback_groups = [[row] for row in fallback]
    return primary_groups, fallback_groups


def process_job(job: dict[str, Any]) -> dict[str, Any]:
    track = _track_context(job)
    providers_tried: list[str] = []
    errors: list[str] = []
    if job_cancel_requested(int(job["id"])):
        set_job_state(int(job["id"]), "cancelled", error="operator_cancelled")
        return {"ok": False, "track_id": int(job["track_id"]), "status": "cancelled"}

    primary_groups, fallback_groups = _provider_groups()
    for group in [*primary_groups, *fallback_groups]:
        if not group:
            continue
        search_results = _search_group(group, track)
        accepted: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for result in search_results:
            provider_name = str(result.get("provider") or "unknown")
            if provider_name != "unknown" and provider_name not in providers_tried:
                providers_tried.append(provider_name)
            error = result.get("error")
            if error:
                errors.append(f"{provider_name}: {error}")
            priority = int((result.get("provider_row") or {}).get("priority") or 999)
            for item in result.get("accepted") or []:
                accepted.append((priority, result, item))
        accepted.sort(key=lambda value: (-float(value[2]["decision"].score), value[0]))
        for _, result, item in accepted:
            if job_cancel_requested(int(job["id"])):
                set_job_state(int(job["id"]), "cancelled", error="operator_cancelled", providers_tried=providers_tried)
                return {"ok": False, "track_id": int(job["track_id"]), "status": "cancelled"}
            try:
                completed = _try_candidate(job, track, result, item)
                completed["providers_tried"] = providers_tried
                set_job_state(int(job["id"]), "completed", providers_tried=providers_tried)
                return completed
            except Exception as exc:
                errors.append(f"{result.get('provider')}: {exc}")
                continue
        # Geen acceptabele kandidaat in deze groep: pas dan de volgende groep proberen.

    attempt = int(job.get("attempts") or 0) + 1
    backoff = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
    next_attempt = (_utcnow() + timedelta(seconds=backoff)).isoformat()
    message = " | ".join(errors)[-3000:] or "Geen provider leverde een voldoende betrouwbare kandidaat."
    set_job_state(
        int(job["id"]),
        "waiting_retry",
        error=message,
        next_attempt_at=next_attempt,
        providers_tried=providers_tried,
        increment_attempts=True,
    )
    with connect() as con:
        con.execute(
            "UPDATE tracks SET download_status='failed',download_attempts=download_attempts+1,error_message=?,updated_at=? WHERE id=?",
            (message, now_iso(), int(job["track_id"])),
        )
    return {
        "ok": False,
        "track_id": int(job["track_id"]),
        "status": "waiting_retry",
        "retry_seconds": backoff,
        "providers_tried": providers_tried,
        "error": message,
    }


def _write_state(*, state: str, results: list[dict[str, Any]] | None = None, error: str | None = None) -> None:
    try:
        from .download_db import provider_dashboard

        dashboard = provider_dashboard()
        jobs = dashboard.get("jobs") or {}
        payload = {
            "state": state,
            "workers": MAX_GLOBAL_DOWNLOADS,
            "queue": int(jobs.get("queued", 0)) + int(jobs.get("searching", 0)),
            "running": sum(int(jobs.get(key, 0)) for key in ("searching", "downloading", "validating", "processing")),
            "retry": int(jobs.get("waiting_retry", 0)),
            "youtube_errors": sum(
                int(item.get("consecutive_errors") or 0)
                for item in dashboard.get("providers", [])
                if item.get("provider") in {"youtube", "youtube_music"}
            ),
            "youtube_dependency_percent": dashboard.get("youtube_dependency_percent"),
            "results": (results or [])[-20:],
            "error": error,
            "updated_at": now_iso(),
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def run_download_manager(batch_limit: int = 20, idle_seconds: float = 5.0) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "download-temp").mkdir(parents=True, exist_ok=True)
    init_download_db()
    with MANAGER_LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Er draait al een Top40 downloadmanager")

        _write_state(state="started")
        while True:
            try:
                if scope_held("downloads"):
                    _write_state(state="operator_hold")
                    time.sleep(max(5.0, idle_seconds))
                    continue

                enqueue_pending_tracks(max(100, batch_limit * 5))
                jobs = claim_jobs(min(MAX_GLOBAL_DOWNLOADS, max(1, int(batch_limit))))
                if not jobs:
                    _write_state(state="idle")
                    time.sleep(max(2.0, idle_seconds))
                    continue

                results: list[dict[str, Any]] = []
                with ThreadPoolExecutor(
                    max_workers=min(MAX_GLOBAL_DOWNLOADS, len(jobs)),
                    thread_name_prefix="download-job",
                ) as executor:
                    futures = {executor.submit(process_job, job): int(job["track_id"]) for job in jobs}
                    for future in as_completed(futures):
                        track_id = futures[future]
                        try:
                            results.append(future.result())
                        except Exception as exc:
                            results.append({"ok": False, "track_id": track_id, "status": "worker_error", "error": str(exc)[-2000:]})
                _write_state(state="processed", results=results)
                time.sleep(0.5)
            except Exception as exc:
                _write_state(state="error", error=str(exc)[-3000:])
                time.sleep(max(5.0, idle_seconds))


if __name__ == "__main__":
    run_download_manager()
