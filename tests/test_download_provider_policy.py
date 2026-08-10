from pathlib import Path

from app.providers import DEFAULT_PROVIDER_CONFIG
from app.providers.base import _category_from_output

ROOT = Path(__file__).resolve().parents[1]


def test_direct_youtube_is_first_provider_with_large_priority_gap():
    priorities = {name: int(cfg["priority"]) for name, cfg in DEFAULT_PROVIDER_CONFIG.items()}
    assert priorities["youtube"] == min(priorities.values())
    assert priorities["youtube"] < priorities["youtube_music"]
    assert priorities["youtube_music"] < priorities["soundcloud"]
    assert priorities["soundcloud"] < priorities["audiomack"]
    assert priorities["audiomack"] < priorities["audius"]
    assert priorities["audius"] < priorities["bandcamp"]
    assert priorities["youtube_music"] - priorities["youtube"] > 20


def test_youtube_family_has_single_concurrent_slot_and_slow_pacing():
    for name in ("youtube_music", "youtube"):
        cfg = DEFAULT_PROVIDER_CONFIG[name]
        assert cfg["max_concurrent"] == 1
        assert cfg["min_delay_seconds"] >= 20
        assert cfg["requests_per_minute"] <= 3


def test_fallback_providers_have_independent_bounded_capacity():
    assert DEFAULT_PROVIDER_CONFIG["soundcloud"]["max_concurrent"] == 2
    assert DEFAULT_PROVIDER_CONFIG["audiomack"]["max_concurrent"] == 2
    assert DEFAULT_PROVIDER_CONFIG["audius"]["max_concurrent"] == 2
    assert DEFAULT_PROVIDER_CONFIG["bandcamp"]["max_concurrent"] == 1


def test_drm_is_classified_as_candidate_specific_error():
    assert _category_from_output("ERROR: This video is DRM protected") == "drm"


def test_provider_ai_keeps_direct_youtube_fixed_first_without_bypass_capabilities():
    source = (ROOT / "app/provider_ai.py").read_text(encoding="utf-8")
    assert 'FIXED_FIRST_PROVIDER = "youtube"' in source
    assert 'if provider == FIXED_FIRST_PROVIDER:' in source
    assert "adjustment = 0" in source
    assert '"youtube_fixed_first": True' in source
    assert '"youtube_max_concurrent": 1' in source
    assert '"accounts_allowed": False' in source
    assert '"cookies_allowed": False' in source
    assert '"captcha_bypass_allowed": False' in source
    assert '"proxy_rotation_allowed": False' in source
    assert '"rate_limit_bypass_allowed": False' in source
    assert "MAX_COOLDOWN_MINUTES = 120" in source


def test_safe_action_has_no_provider_bypass_action():
    source = (ROOT / "scripts/top40-safe-action").read_text(encoding="utf-8").casefold()
    assert '"captcha_bypass_allowed": false' in source
    assert '"proxy_rotation_allowed": false' in source
    assert '"rate_limit_bypass_allowed": false' in source
    assert "rotate_proxy" not in source
    assert "solve_captcha" not in source
