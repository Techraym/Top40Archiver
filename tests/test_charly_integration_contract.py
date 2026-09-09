from __future__ import annotations

import base64
import hashlib
import io
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "charly-v0.2.0"
EXPECTED_B64_SHA = "26c06d816aa1f8b3b6056fa8599ac08010a37a0df82067951c09e6606f776962"
EXPECTED_TGZ_SHA = "e11271203dce95c49cc8c68d62135a42afe505bf3995df703139b22572a16fea"


def test_release_declares_charly_version():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.16.23"
    release_installer = ROOT / "scripts" / "install-1.16.23.sh"
    integration_installer = ROOT / "scripts" / "install-charly-top40.sh"
    assert release_installer.exists()
    assert integration_installer.exists()
    assert "install-charly-top40.sh" in release_installer.read_text(encoding="utf-8")


def test_charly_installers_have_valid_shell_syntax():
    for script in (
        ROOT / "scripts" / "install-1.16.23.sh",
        ROOT / "scripts" / "install-charly-top40.sh",
    ):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_vendored_charly_archive_is_exact_and_complete():
    parts = sorted(VENDOR.glob("part-*.b64"))
    assert [p.name for p in parts] == [f"part-{i:02d}.b64" for i in range(8)]

    encoded = b"".join(p.read_bytes() for p in parts)
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED_B64_SHA

    archive = base64.b64decode(encoded, validate=True)
    assert hashlib.sha256(archive).hexdigest() == EXPECTED_TGZ_SHA

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        names = set(tf.getnames())

    required = {
        "charly-v0.2/charly/agent.py",
        "charly-v0.2/charly/api.py",
        "charly-v0.2/charly/router.py",
        "charly-v0.2/charly/gateway.py",
        "charly-v0.2/charly/gateway_main.py",
        "charly-v0.2/scripts/install-debian.sh",
        "charly-v0.2/scripts/install-ollama-gateway.sh",
        "charly-v0.2/systemd/charly-core.service",
        "charly-v0.2/systemd/charly-ollama-gateway.service",
    }
    assert required <= names


def test_charly_gateway_contract_preserves_existing_ollama_clients():
    installer = (ROOT / "scripts" / "install-charly-top40.sh").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "CHARLY.md").read_text(encoding="utf-8")

    for marker in (
        "127.0.0.1:11434",
        "127.0.0.1:11435",
        "charly-ollama-gateway.service",
        "http://127.0.0.1:8765/api/health",
        "http://127.0.0.1:8041/healthz",
    ):
        assert marker in installer

    assert "11434" in docs
    assert "11435" in docs
    assert "Qwen" in docs
    assert "CHARLY" in docs


def test_charly_install_has_rollback_and_does_not_touch_audio_library():
    installer = (ROOT / "scripts" / "install-charly-top40.sh").read_text(encoding="utf-8")
    assert "rollback" in installer
    assert "ollama-charly-backend.conf" in installer
    assert "audio_library_touched=false" in installer
    assert "/mnt/top40-music" not in installer


def test_vendored_checksums_are_documented():
    sums = (VENDOR / "SHA256SUMS").read_text(encoding="utf-8")
    assert EXPECTED_B64_SHA in sums
    assert EXPECTED_TGZ_SHA in sums
