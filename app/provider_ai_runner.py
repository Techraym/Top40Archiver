from __future__ import annotations

import json

from .ai_learning import new_cycle_id
from .provider_ai import run_provider_ai_tuning


def main() -> None:
    print(json.dumps(run_provider_ai_tuning(new_cycle_id()), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
