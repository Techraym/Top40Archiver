from __future__ import annotations

import json

from .incident_engine import scan_journal


def main() -> None:
    print(json.dumps(scan_journal(minutes=20), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
