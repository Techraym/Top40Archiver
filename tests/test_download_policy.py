from pathlib import Path

from app import download_manager_dynamic_entry, download_policy

ROOT = Path(__file__).resolve().parents[1]


def test_current_top40_is_claimed_before_tipparade_and_archive():
    source = (ROOT / "app/download_policy.py").read_text(encoding="utf-8")
    claim = source[source.index("def claim_jobs_current_first") :]
    top_case = claim.index("FROM chart_entries ce")
    tip_case = claim.index("FROM tipparade_entries te")
    archive_case = claim.index("ELSE 'archive'")
    assert top_case < tip_case < archive_case
    assert "queue_class" in claim
    assert 'THEN 0' in claim
    assert 'THEN 1' in claim
    assert 'ELSE 2' in claim


def test_claim_batch_never_mixes_archive_with_ready_current_chart_work():
    source = (ROOT / "app/download_policy.py").read_text(encoding="utf-8")
    claim = source[source.index("def claim_jobs_current_first") : source.index("def apply_current_chart_fast_retry")]
    assert 'selected_class = str(rows[0]["queue_class"])' in claim
    assert 'if str(row["queue_class"]) == selected_class' in claim
    assert "[:wanted]" in claim


def test_pending_enqueue_uses_same_current_chart_priority():
    source = (ROOT / "app/download_policy.py").read_text(encoding="utf-8")
    enqueue = source[
        source.index("def enqueue_pending_tracks_current_first") :
        source.index("def claim_jobs_current_first")
    ]
    assert "chart_entries ce" in enqueue
    assert "tipparade_entries te" in enqueue
    assert "THEN 0" in enqueue
    assert "THEN 1" in enqueue
    assert "ELSE 2" in enqueue


def test_current_chart_fast_retry_is_short_and_bounded():
    source = (ROOT / "app/download_policy.py").read_text(encoding="utf-8")
    assert "CURRENT_TOP40_FAST_RETRY_SECONDS = 20" in source
    assert "CURRENT_TIPPARADE_FAST_RETRY_SECONDS = 30" in source
    assert "CURRENT_CHART_FAST_RETRY_ATTEMPTS = 5" in source
    retry = source[source.index("def apply_current_chart_fast_retry") :]
    assert "download_status='pending'" in retry
    assert 'updated["fast_retry"] = True' in retry
    assert "attempts > CURRENT_CHART_FAST_RETRY_ATTEMPTS" in retry


def test_dynamic_manager_applies_fast_retry_to_real_process_job_result():
    source = (ROOT / "app/download_manager_dynamic_entry.py").read_text(encoding="utf-8")
    assert "def _run_one_job" in source
    assert "result = download_manager.process_job(job)" in source
    assert "return apply_current_chart_fast_retry(job, result)" in source
    assert '"single_queue_class_per_batch": True' in source
    assert '"current_chart_fast_retry": True' in source


def test_youtube_gets_exclusive_first_provider_group(monkeypatch):
    rows = [
        {"provider": "soundcloud", "priority": 80, "ai_priority_adjustment": -20},
        {"provider": "youtube_music", "priority": 40, "ai_priority_adjustment": -20},
        {"provider": "youtube", "priority": 10, "ai_priority_adjustment": 20},
    ]
    monkeypatch.setattr(
        download_manager_dynamic_entry.download_manager,
        "provider_configs",
        lambda enabled_only=True: list(rows),
    )
    monkeypatch.setattr(
        download_manager_dynamic_entry.download_manager,
        "_provider_available",
        lambda row: True,
    )

    primary, fallback = download_manager_dynamic_entry._youtube_first_provider_groups()

    assert [row["provider"] for row in primary[0]] == ["youtube"]
    assert fallback == []
    assert {row["provider"] for group in primary[1:] for row in group} == {
        "youtube_music",
        "soundcloud",
    }


def test_transient_transport_error_does_not_permanently_reject_candidate(monkeypatch):
    stored = []
    monkeypatch.setattr(
        download_manager_dynamic_entry,
        "_store_rejected_candidate",
        lambda *args, **kwargs: stored.append((args, kwargs)),
    )

    for reason in sorted(download_policy.TRANSIENT_CANDIDATE_ERRORS):
        download_manager_dynamic_entry._persistent_reject_candidate(
            1, "youtube", "https://example.invalid/video", reason, 99.0
        )
    assert stored == []

    download_manager_dynamic_entry._persistent_reject_candidate(
        1, "youtube", "https://example.invalid/drm", "drm", 99.0
    )
    download_manager_dynamic_entry._persistent_reject_candidate(
        1, "youtube", "https://example.invalid/gone", "unavailable", 99.0
    )
    assert len(stored) == 2


def test_provider_policy_migration_clears_old_transient_rejects_only():
    source = (ROOT / "app/download_policy.py").read_text(encoding="utf-8")
    assert 'PROVIDER_ORDER_POLICY = "youtube_first_v1"' in source
    assert "DELETE FROM rejected_candidates WHERE reason IN" in source
    assert '"drm"' not in source[source.index("TRANSIENT_CANDIDATE_ERRORS") : source.index("def ensure_provider_order_policy")]
    assert '"unavailable"' not in source[source.index("TRANSIENT_CANDIDATE_ERRORS") : source.index("def ensure_provider_order_policy")]


def test_manager_installs_current_chart_and_retry_policy_before_processing():
    source = (ROOT / "app/download_manager_dynamic_entry.py").read_text(encoding="utf-8")
    assert "download_manager.enqueue_pending_tracks = enqueue_pending_tracks_current_first" in source
    assert "download_manager.claim_jobs = claim_jobs_current_first" in source
    assert "download_manager._provider_groups = _youtube_first_provider_groups" in source
    assert "download_manager.reject_candidate = _persistent_reject_candidate" in source
    assert 'first_provider=FIRST_PROVIDER' in source
    assert 'queue_priority="current_top40,current_tipparade,archive"' in source
    assert "transient_candidate_retry=True" in source
