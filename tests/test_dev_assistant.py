from pathlib import Path

import pytest

from app import dev_assistant


def test_rejects_parent_paths():
    with pytest.raises(ValueError):
        dev_assistant._allowed_relative("../etc/passwd")


def test_rejects_binary_and_secret_paths():
    with pytest.raises(ValueError):
        dev_assistant._allowed_relative("downloads/test.mp3")
    with pytest.raises(ValueError):
        dev_assistant._allowed_relative("secrets/token.txt")


def test_accepts_application_source():
    assert dev_assistant._allowed_relative("app/main.py") == Path("app/main.py")


def test_patch_requires_unified_diff(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_assistant, "WORKSPACES", tmp_path)
    workspace_id = "a" * 32
    (tmp_path / workspace_id / "source").mkdir(parents=True)
    with pytest.raises(ValueError):
        dev_assistant.save_patch(workspace_id, "print('not a diff')", "test")


def test_pr_plan_requires_successful_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_assistant, "WORKSPACES", tmp_path)
    workspace_id = "b" * 32
    base = tmp_path / workspace_id
    base.mkdir(parents=True)
    with pytest.raises(ValueError):
        dev_assistant.create_pr_plan(workspace_id, "Titel", "Beschrijving van de wijziging")
