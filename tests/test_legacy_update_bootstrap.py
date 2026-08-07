from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_current_release_has_legacy_version_bootstrap():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    installer = ROOT / "scripts" / f"install-{version}.sh"
    assert installer.is_file(), f"legacy updater requires {installer.relative_to(ROOT)}"

    source = installer.read_text(encoding="utf-8")
    assert "legacy" in source.lower()
    assert "previous-sha" in source
    assert "version-rollback" in source
    assert "BACKUP_OK" in source
    assert "audio_library_touched" in source
    assert "TOP40_SOURCE_SHA" in source
    assert 'bash "$TMP/update-existing.sh"' in source
    assert "top40-archiver-safe-update" in source


def test_legacy_bootstrap_never_touches_downloaded_audio_library():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    source = (ROOT / "scripts" / f"install-{version}.sh").read_text(encoding="utf-8")
    assert '"audio_library_touched": False' in source
    assert "rm -rf /var/lib/top40-archiver/download" not in source
    assert "rm -rf /var/lib/top40-archiver/downloads" not in source
