from __future__ import annotations

import json

from . import download_manager
from . import download_manager_dynamic_entry as dynamic
from .charly_download_control import (
    apply_retry_policy,
    claim_jobs_background_safe,
    control_state_summary,
    prepare_recovery_query,
)

_INSTALLED = False


def _decorate_state_file() -> None:
    try:
        path = download_manager.STATE_FILE
        if not path.is_file():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["charly_control_layer"] = True
        payload["charly_recovery"] = control_state_summary()
        tmp = path.with_suffix(".charly.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _install_control_layer() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    original_install_policy = dynamic._install_download_policy
    original_write_state = dynamic._write_state

    def install_policy() -> None:
        original_install_policy()
        download_manager.prepare_recovery_query = prepare_recovery_query
        download_manager.claim_jobs = claim_jobs_background_safe
        dynamic.apply_current_chart_fast_retry = apply_retry_policy

    def write_state(*, state, results=None, error=None, worker_config=None) -> None:
        original_write_state(state=state,results=results,error=error,worker_config=worker_config)
        _decorate_state_file()

    dynamic._install_download_policy = install_policy
    dynamic._write_state = write_state
    _INSTALLED = True


def main() -> None:
    _install_control_layer()
    dynamic.main()


if __name__ == "__main__":
    main()
