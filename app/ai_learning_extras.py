from __future__ import annotations

from .ai_learning import record_action


def record_recovery_side_effects(cycle_id: str, recovery_report: dict) -> int:
    """Registreer beheerwijzigingen die onderdeel zijn van een grotere herstelactie.

    De downloadhersteller kan bijvoorbeeld automatisch het aantal workers verlagen bij
    rate limiting. Dat is een afzonderlijke beheeractie en moet daarom ook afzonderlijk
    worden geleerd en later beoordeeld.
    """
    recorded = 0
    verification = recovery_report.get("verification") or {}
    for item in recovery_report.get("actions") or []:
        before = item.get("workers_before")
        after = item.get("workers_after")
        if before is None or after is None:
            continue
        try:
            before_i = int(before)
            after_i = int(after)
        except (TypeError, ValueError):
            continue
        if before_i == after_i:
            continue

        restart = item.get("restart") or {"ok": True}
        success = bool(restart.get("ok", True))
        record_action(
            cycle_id=cycle_id,
            domain="download_settings",
            problem_key="downloads:adaptive_worker_load",
            action=f"set_workers_{after_i}",
            reason=(
                "AI paste de downloadbelasting automatisch aan als onderdeel van fout-herstel; "
                "deze instelling wordt afzonderlijk geleerd."
            ),
            subject="download_workers",
            before={"workers": before_i},
            after={"workers": after_i, "verification": verification},
            result={"parent_action": item.get("action"), "restart": restart},
            success=success,
            effect_score=0.8 if success else 0.0,
            operator_needed=not success,
            reversible=True,
        )
        recorded += 1
    return recorded
