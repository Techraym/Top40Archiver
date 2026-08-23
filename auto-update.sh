#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Voer dit script als root uit."
  exit 1
fi

REPO="Techraym/Top40Archiver"
APP_ROOT="/opt/top40-archiver"
REMOTE="${TOP40_UPDATE_REMOTE:-origin}"
REQUESTED_BRANCH="${TOP40_UPDATE_BRANCH:-}"
BRANCH=""
LOCAL_VERSION_FILE="$APP_ROOT/VERSION"
STATE_DIR="/var/lib/top40-archiver/update-state"
INSTALLED_SHA_FILE="$STATE_DIR/installed_commit_sha"
LAST_CHECK_FILE="$STATE_DIR/last_check"
LAST_REMOTE_SHA_FILE="$STATE_DIR/last_remote_commit_sha"
LAST_ARCHIVE_SHA_FILE="$STATE_DIR/last_archive_sha256"
LAST_SUCCESS_FILE="$STATE_DIR/last_success"
LOCK_FILE="/run/lock/top40-archiver-auto-update.lock"
FORCE=0

if [ "${1:-}" = "--force" ]; then
  FORCE=1
elif [ -n "${1:-}" ]; then
  echo "Gebruik: $0 [--force]"
  exit 2
fi

mkdir -p "$STATE_DIR" "$(dirname "$LOCK_FILE")"
chmod 755 "$STATE_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Er draait al een Top40Archiver-updatecontrole."
  exit 0
fi

for command in curl unzip python3 sha256sum git; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "FOUT: vereist commando ontbreekt: $command"
    exit 1
  fi
done

resolve_update_branch() {
  if [ -n "$REQUESTED_BRANCH" ]; then
    BRANCH="$REQUESTED_BRANCH"
  else
    local upstream
    upstream="$(
      git         -c safe.directory="$APP_ROOT"         -C "$APP_ROOT"         rev-parse         --abbrev-ref         --symbolic-full-name         '@{u}'         2>/dev/null || true
    )"

    case "$upstream" in
      "$REMOTE/"*)
        BRANCH="${upstream#"$REMOTE/"}"
        ;;
      *)
        echo "FOUT: geen expliciet TOP40_UPDATE_BRANCH en huidige productiebranch heeft geen upstream op remote $REMOTE; update afgebroken."
        return 19
        ;;
    esac
  fi

  if ! git check-ref-format --branch "$BRANCH" >/dev/null 2>&1; then
    echo "FOUT: ongeldig Top40Archiver-updatekanaal: $BRANCH"
    return 19
  fi

  echo "Updatekanaal: $REMOTE/$BRANCH"
}

resolve_update_branch

printf '%s\n' "$(date -Is)" > "$LAST_CHECK_FILE"

echo "GitHub-commit controleren voor ${REPO}:${BRANCH}..."
REMOTE_SHA=$(
  curl --fail --silent --show-error --location --retry 3 \
    --connect-timeout 15 --max-time 60 \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: Top40Archiver-AutoUpdater' \
    "https://api.github.com/repos/${REPO}/commits/${BRANCH}" |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["sha"])'
)

if [[ ! "$REMOTE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "FOUT: GitHub gaf geen geldige commit-SHA terug: $REMOTE_SHA"
  exit 1
fi

REMOTE_VERSION=$(
  curl --fail --silent --show-error --location --retry 3 \
    --connect-timeout 15 --max-time 60 \
    -H 'User-Agent: Top40Archiver-AutoUpdater' \
    "https://raw.githubusercontent.com/${REPO}/${REMOTE_SHA}/VERSION" |
  tr -d '\r\n[:space:]'
)
if [ -z "$REMOTE_VERSION" ]; then
  echo "FOUT: GitHub gaf geen geldig versienummer voor commit $REMOTE_SHA."
  exit 1
fi

printf '%s\n' "$REMOTE_SHA" > "$LAST_REMOTE_SHA_FILE"
LOCAL_SHA=""
LOCAL_VERSION=""
if [ -f "$INSTALLED_SHA_FILE" ]; then
  LOCAL_SHA=$(tr -d '[:space:]' < "$INSTALLED_SHA_FILE")
fi
if [ -f "$LOCAL_VERSION_FILE" ]; then
  LOCAL_VERSION=$(tr -d '[:space:]' < "$LOCAL_VERSION_FILE")
fi

if [ "$FORCE" -eq 0 ] \
  && [ "$LOCAL_SHA" = "$REMOTE_SHA" ] \
  && [ "$LOCAL_VERSION" = "$REMOTE_VERSION" ]; then
  echo "Top40Archiver is actueel: versie $LOCAL_VERSION, commit $REMOTE_SHA"
  exit 0
fi

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ] && [ "$LOCAL_VERSION" != "$REMOTE_VERSION" ]; then
  echo "Lokale installatie is inconsistent en wordt automatisch hersteld:"
  echo "  geregistreerde commit: $LOCAL_SHA"
  echo "  lokale versie:         ${LOCAL_VERSION:-ontbreekt}"
  echo "  GitHub-versie:         $REMOTE_VERSION"
elif [ -n "$LOCAL_SHA" ]; then
  echo "Update beschikbaar:"
  echo "  lokaal:  $LOCAL_SHA (${LOCAL_VERSION:-onbekend})"
  echo "  GitHub:  $REMOTE_SHA ($REMOTE_VERSION)"
else
  echo "Nog geen lokaal geïnstalleerde commit-SHA geregistreerd."
  echo "GitHub-versie wordt eenmalig opnieuw geïnstalleerd: $REMOTE_SHA"
fi

TMP_DIR=$(mktemp -d /tmp/top40-archiver-auto-update.XXXXXX)
ARCHIVE="$TMP_DIR/source-${REMOTE_SHA}.zip"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Vastgepinde GitHub-versie downloaden..."
curl --fail --location --retry 3 \
  --connect-timeout 15 --max-time 600 \
  "https://github.com/${REPO}/archive/${REMOTE_SHA}.zip" \
  --output "$ARCHIVE"

ARCHIVE_SHA256=$(sha256sum "$ARCHIVE" | awk '{print $1}')
if [[ ! "$ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "FOUT: geen geldige SHA-256 voor het updatearchief."
  exit 1
fi

echo "Archief SHA-256: $ARCHIVE_SHA256"
unzip -q "$ARCHIVE" -d "$TMP_DIR"

SOURCE_DIR=$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'Top40Archiver-*' | head -n 1)
if [ -z "$SOURCE_DIR" ] || [ ! -f "$SOURCE_DIR/update-existing.sh" ]; then
  echo "FOUT: update-existing.sh ontbreekt in het vastgepinde GitHub-archief."
  exit 1
fi

SOURCE_VERSION=$(tr -d '[:space:]' < "$SOURCE_DIR/VERSION")
if [ "$SOURCE_VERSION" != "$REMOTE_VERSION" ]; then
  echo "FOUT: versie in het archief ($SOURCE_VERSION) wijkt af van GitHub ($REMOTE_VERSION)."
  exit 1
fi

chmod +x "$SOURCE_DIR/update-existing.sh"

echo "Update installeren..."
TOP40_SOURCE_SHA="$REMOTE_SHA" \
TOP40_ARCHIVE_SHA256="$ARCHIVE_SHA256" \
  "$SOURCE_DIR/update-existing.sh"

APPLIED_SHA=""
APPLIED_VERSION=""
if [ -f "$INSTALLED_SHA_FILE" ]; then
  APPLIED_SHA=$(tr -d '[:space:]' < "$INSTALLED_SHA_FILE")
fi
if [ -f "$LOCAL_VERSION_FILE" ]; then
  APPLIED_VERSION=$(tr -d '[:space:]' < "$LOCAL_VERSION_FILE")
fi

if [ "$APPLIED_SHA" != "$REMOTE_SHA" ]; then
  echo "FOUT: geïnstalleerde SHA ($APPLIED_SHA) komt niet overeen met GitHub-SHA ($REMOTE_SHA)."
  exit 1
fi
if [ "$APPLIED_VERSION" != "$REMOTE_VERSION" ]; then
  echo "FOUT: geïnstalleerde versie ($APPLIED_VERSION) komt niet overeen met GitHub-versie ($REMOTE_VERSION)."
  exit 1
fi

printf '%s\n' "$ARCHIVE_SHA256" > "$LAST_ARCHIVE_SHA_FILE"
printf '%s\n' "$(date -Is)" > "$LAST_SUCCESS_FILE"

echo "Top40Archiver is bijgewerkt naar versie $REMOTE_VERSION, commit $REMOTE_SHA"
