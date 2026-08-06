#!/usr/bin/env bash
set -euo pipefail
DB="/var/lib/top40-archiver/top40.sqlite3"
LIMIT="${1:-50}"
sudo -u top40archiver sqlite3 -header -column "$DB" "
SELECT
  created_at AS tijd,
  category AS categorie,
  status,
  artist,
  title,
  attempts AS pogingen,
  substr(replace(reason,char(10),' '),1,180) AS reden
FROM download_rejection_log
ORDER BY id DESC
LIMIT $LIMIT;
"
