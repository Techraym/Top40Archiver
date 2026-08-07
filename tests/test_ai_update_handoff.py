import json

from app import ai_memory, ai_update_handoff
from app.ai_learning import start_action


def test_official_update_neutrally_supersedes_active_code_canary(tmp_path, monkeypatch):
    memory = tmp_path / "ai_memory.sqlite"
    monkeypatch.setattr(ai_memory, "AI_MEMORY_PATH", memory)
    repair_state = tmp_path / "code-repair-state.json"
    improvement_state = tmp_path / "code-improvement-state.json"
    monkeypatch.setattr(ai_update_handoff, "STATE_FILES", (repair_state, improvement_state))

    action_id = start_action(
        cycle_id="cycle-code",
        domain="code",
        problem_key="code:abc",
        action="promote_validated_patch",
        reason="canary",
        subject="abc",
        before={"health": True},
        reversible=True,
    )
    repair_state.write_text(
        json.dumps({
            "active": {
                "action_id": action_id,
                "workspace_id": "ws-1",
                "fingerprint": "abc",
                "files": ["app/downloader.py"],
            },
            "seen": {},
        }),
        encoding="utf-8",
    )

    result = ai_update_handoff.handoff_official_update("1.16.5", "deadbeef")
    assert result["ok"] is True
    assert len(result["superseded"]) == 1

    state = json.loads(repair_state.read_text(encoding="utf-8"))
    assert state["active"] is None
    assert state["last_superseded"]["version"] == "1.16.5"

    with ai_memory.connect() as conn:
        row = conn.execute("SELECT status,success,result_json FROM action_execution WHERE id=?", (action_id,)).fetchone()
        learned = conn.execute("SELECT COUNT(*) FROM action_learning WHERE problem_key='code:abc'").fetchone()[0]
    assert row["status"] == "superseded"
    assert row["success"] is None
    assert "superseded_by_official_update" in row["result_json"]
    # Een officiële release die een canary vervangt is neutraal bewijs en mag de
    # effectiviteit van de lokale patch niet positief of negatief vertekenen.
    assert learned == 0
