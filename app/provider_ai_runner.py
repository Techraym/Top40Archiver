from __future__ import annotations

import json

from .ai_learning import new_cycle_id
from .download_concurrency_ai import run_download_concurrency_ai
from .provider_ai import run_provider_ai_tuning


def main() -> None:
    cycle_id = new_cycle_id()
    result = {
        "provider_tuning": run_provider_ai_tuning(cycle_id),
        "download_concurrency": run_download_concurrency_ai(cycle_id),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
