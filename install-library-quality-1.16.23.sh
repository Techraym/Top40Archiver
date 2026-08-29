#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

ROOT="$(cd "$(dirname "$0")" && pwd)"
EXPECTED_SHA256="1487c41ba019ddf8273063ef14bf9f5971dd2ae381e9dbe33d48db5c62d6f60c"
EXPECTED_BASE_COMMIT="609d299e8b5eb625f0c4ab6d5e67c1ca352befe2"
STATE_DIR="/var/lib/top40-archiver/update-state"
PATCH_SCRIPT="$ROOT/scripts/patch-library-quality-max-files.py"
HOTFIX_SCRIPT="$ROOT/update-library-quality-1.16.23.2.sh"
HOTFIX_1233_SCRIPT="$ROOT/update-library-quality-1.16.23.3.sh"
HOTFIX_1234_SCRIPT="$ROOT/update-library-quality-1.16.23.4.sh"
VENV_PY="/opt/top40-archiver/venv/bin/python"

[ "$(id -u)" -eq 0 ] || { echo "Voer uit met sudo/root."; exit 1; }

ACTIVE_COMMIT="$(tr -d '[:space:]' < "$STATE_DIR/installed_commit_sha" 2>/dev/null || true)"
if [ "$ACTIVE_COMMIT" != "$EXPECTED_BASE_COMMIT" ]; then
  echo "FOUT: actieve Top40Archiver-basis wijkt af van de geteste basis."
  echo "Verwacht: $EXPECTED_BASE_COMMIT"
  echo "Actief:    ${ACTIVE_COMMIT:-niet geregistreerd}"
  exit 1
fi

PARTS=("$ROOT"/releases/library-quality-payload.part-*)
if [ "${#PARTS[@]}" -ne 13 ]; then
  echo "FOUT: verwacht 13 GitHub-payloaddelen, gevonden ${#PARTS[@]}."
  exit 1
fi
[ -f "$PATCH_SCRIPT" ] || { echo "FOUT: veiligheids-patch ontbreekt: $PATCH_SCRIPT"; exit 1; }
[ -f "$HOTFIX_SCRIPT" ] || { echo "FOUT: Library Quality 1.16.23.2 hotfix ontbreekt: $HOTFIX_SCRIPT"; exit 1; }
[ -f "$HOTFIX_1233_SCRIPT" ] || { echo "FOUT: Library Quality 1.16.23.3 hotfix ontbreekt: $HOTFIX_1233_SCRIPT"; exit 1; }
[ -f "$HOTFIX_1234_SCRIPT" ] || { echo "FOUT: Library Quality 1.16.23.4 hotfix ontbreekt: $HOTFIX_1234_SCRIPT"; exit 1; }

TMP="$(mktemp -d /tmp/top40-library-quality-github.XXXXXX)"
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT
ARCHIVE="$TMP/top40-library-quality-8085-1.16.23.tar.gz"

cat "${PARTS[@]}" | base64 --decode > "$ARCHIVE"
ACTUAL_SHA256="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
  echo "FOUT: SHA-256 na GitHub-decodering klopt niet."
  echo "Verwacht: $EXPECTED_SHA256"
  echo "Gevonden: $ACTUAL_SHA256"
  exit 1
fi

tar -tzf "$ARCHIVE" >/dev/null
tar -xzf "$ARCHIVE" -C "$TMP"
PKG="$TMP/top40-library-quality-8085-1.16.23"
[ -f "$PKG/install.sh" ] || { echo "FOUT: install.sh ontbreekt in Library Quality pakket."; exit 1; }

echo "GitHub payload gecontroleerd: $ACTUAL_SHA256"
echo "Geteste Top40Archiver-basis: $ACTIVE_COMMIT"
bash "$PKG/install.sh"

# Extra veiligheidslaag voor gecontroleerde eerste productieruns.
"$VENV_PY" "$PATCH_SCRIPT"
"$VENV_PY" -m py_compile /opt/top40-archiver/app/library_quality.py
PYTHONPATH=/opt/top40-archiver "$VENV_PY" -m app.library_quality scan --help | grep -q -- '--max-files'
systemctl restart top40-library-quality.service
curl -fsS --retry 10 --retry-delay 1 http://127.0.0.1:8085/healthz >/dev/null

echo "Library Quality batchbegrenzing actief: --max-files"

echo
echo "=== Aanvullende Library Quality 1.16.23.2 hotfix ==="
bash "$HOTFIX_SCRIPT"

echo
echo "=== Aanvullende Library Quality 1.16.23.3 Top40.nl cover bridge ==="
bash "$HOTFIX_1233_SCRIPT"

echo
echo "=== Aanvullende Library Quality 1.16.23.4 stale-cover fallback ==="
bash "$HOTFIX_1234_SCRIPT"
