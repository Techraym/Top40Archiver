#!/usr/bin/env bash
set -euo pipefail
cd /opt/top40-archiver

echo "=== Lokale Top40Archiver-wijzigingen controleren ==="
if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "STOP: er staan lokale wijzigingen die nog niet in GitHub zijn opgeslagen."
  echo
  git status --short
  echo
  echo "Maak eerst een veiligheidsbranch en commit, bijvoorbeeld:"
  echo "  git switch -c backup/lokale-cover-en-ai-wijzigingen-$(date +%Y%m%d-%H%M)"
  echo "  git add -A"
  echo "  git commit -m 'Bewaar lokale albumcover en AI wijzigingen'"
  exit 2
fi

echo "OK: de werkmap is schoon. Een branchwissel overschrijft geen lokale bestanden."
