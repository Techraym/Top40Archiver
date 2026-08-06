from __future__ import annotations

import subprocess
from dataclasses import dataclass

ALLOWED_UNITS = {
    "all": [
        "top40-archiver-web.service",
        "top40-archiver-ai.service",
        "top40-archiver-download.service",
        "top40-archiver-check.service",
        "top40-archiver-history.service",
        "top40-archiver-cover-art.service",
        "top40-archiver-id3-cover.service",
        "top40-archiver-incident-scan.service",
        "top40-archiver-auto-update.service",
    ],
    "web": ["top40-archiver-web.service"],
    "ai": ["top40-archiver-ai.service"],
    "downloads": ["top40-archiver-download.service"],
    "charts": ["top40-archiver-check.service", "top40-archiver-history.service"],
    "covers": ["top40-archiver-cover-art.service", "top40-archiver-id3-cover.service"],
    "updates": ["top40-archiver-auto-update.service"],
    "incidents": ["top40-archiver-incident-scan.service"],
}

@dataclass(frozen=True)
class LogResult:
    group: str
    minutes: int
    lines: list[str]


def read_logs(group: str = "all", minutes: int = 60, limit: int = 1000) -> LogResult:
    selected = ALLOWED_UNITS.get(group)
    if selected is None:
        raise ValueError(f"Onbekende loggroep: {group}")

    cmd = [
        "journalctl",
        "--no-pager",
        "--output=short-iso",
        "--since",
        f"-{max(1, min(minutes, 1440))} minutes",
        "-n",
        str(max(20, min(limit, 5000))),
    ]
    for unit in selected:
        cmd.extend(["-u", unit])

    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    output = completed.stdout or completed.stderr or "Geen logregels gevonden."
    return LogResult(group=group, minutes=minutes, lines=output.splitlines())


def service_states() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for units in ALLOWED_UNITS.values():
        for unit in units:
            if unit in seen:
                continue
            seen.add(unit)
            completed = subprocess.run(
                ["systemctl", "show", unit, "--property=ActiveState,SubState,Result", "--value"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            values = (completed.stdout or "unknown\nunknown\nunknown").splitlines()
            values += ["unknown"] * (3 - len(values))
            rows.append({"unit": unit, "active": values[0], "sub": values[1], "result": values[2]})
    return rows
