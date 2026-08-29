#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path('/opt/top40-archiver/app/library_quality.py')
if not path.exists():
    raise SystemExit(f'FOUT: {path} ontbreekt')

text = path.read_text(encoding='utf-8')
if '--max-files' in text and 'max_files: int = -1' in text:
    print('Library Quality --max-files is al aanwezig.')
    raise SystemExit(0)

replacements = [
    (
        'def scan_library(trigger: str = "manual", force: bool = False, heavy_limit: int = DEFAULT_HEAVY_LIMIT, enrich_limit: int = DEFAULT_ENRICH_LIMIT, cover_limit: int = DEFAULT_COVER_LIMIT) -> dict[str, Any]:',
        'def scan_library(trigger: str = "manual", force: bool = False, heavy_limit: int = DEFAULT_HEAVY_LIMIT, enrich_limit: int = DEFAULT_ENRICH_LIMIT, cover_limit: int = DEFAULT_COVER_LIMIT, max_files: int = -1) -> dict[str, Any]:',
    ),
    (
        '        files = discover_files(download_dir)\n        tracks = _track_map(download_dir)',
        '        files = discover_files(download_dir)\n        if max_files >= 0:\n            files = files[:max_files]\n        tracks = _track_map(download_dir)',
    ),
    (
        '    scan.add_argument("--cover-limit", type=int, default=DEFAULT_COVER_LIMIT, help="-1 = onbeperkt")',
        '    scan.add_argument("--cover-limit", type=int, default=DEFAULT_COVER_LIMIT, help="-1 = onbeperkt")\n    scan.add_argument("--max-files", type=int, default=-1, help="maximaal aantal audiobestanden voor deze run; -1 = onbeperkt")',
    ),
    (
        '        print(json.dumps(scan_library(args.trigger, args.force, args.heavy_limit, args.enrich_limit, args.cover_limit), ensure_ascii=False, indent=2))',
        '        print(json.dumps(scan_library(args.trigger, args.force, args.heavy_limit, args.enrich_limit, args.cover_limit, args.max_files), ensure_ascii=False, indent=2))',
    ),
]

for old, new in replacements:
    if old not in text:
        print('FOUT: verwachte broncode niet gevonden; patch wordt niet gedeeltelijk toegepast.', file=sys.stderr)
        raise SystemExit(1)
    text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')
print('Library Quality --max-files toegevoegd.')
