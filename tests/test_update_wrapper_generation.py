from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _generator_source() -> str:
    wrapper = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    start_marker = 'python3 - "$GENERATED" "$VERSION" <<\'PY\'\n'
    start = wrapper.index(start_marker) + len(start_marker)
    end = wrapper.index("\nPY\n", start)
    return wrapper[start:end]


def test_release_update_generator_is_valid_python_and_generates_valid_shell(tmp_path):
    source = _generator_source()
    compile(source, "update-existing-generator", "exec")

    generated = tmp_path / "generated-update.sh"
    generated.write_text(
        (ROOT / "scripts/update-existing-1.16-base.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-", str(generated), "1.16.4"],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    shell = subprocess.run(
        ["bash", "-n", str(generated)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert shell.returncode == 0, shell.stderr

    text = generated.read_text(encoding="utf-8")
    for marker in (
        'assert x.get("version") == "1.16.4"',
        'assert x.get("closed_loop_learning") is True',
        'assert x.get("continuous_online_learning") is True',
        'assert x.get("learning_starts_at_action") == 1',
        'assert x.get("chart_freshness_guard") is True',
        'assert x.get("autonomous_code_repair") is True',
        'assert x.get("code_repair_requires_verified_backup") is True',
        'assert x.get("audio_delete_allowed") is False',
        'assert x.get("verified_version_backups") is True',
        "tests/test_ai_learning.py",
        "tests/test_chart_freshness.py",
        "tests/test_ai_code_repair_policy.py",
        "tests/test_version_backup_contract.py",
        "/api/ai/learning",
        "/api/ai/chart-freshness",
        "/api/ai/code-repair",
        "/usr/local/sbin/top40-version-backup",
        "/usr/local/sbin/top40-version-rollback",
        "top40-archiver-freshness.timer",
        "top40-archiver-cover-art.timer",
        "systemctl start --no-block top40-archiver-freshness.service",
    ):
        assert marker in text, marker
