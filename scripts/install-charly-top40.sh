#!/usr/bin/env bash
set -Eeuo pipefail

# Native CHARLY v0.2.0 integration for Top40Archiver.
# No Docker/VM. The music library is never touched by this installer.
# Existing Ollama clients stay on 127.0.0.1:11434; CHARLY becomes the gateway
# and the private Ollama/Qwen backend moves to 127.0.0.1:11435.

APP=/opt/top40-archiver
VENDOR="$APP/vendor/charly-v0.2.0"
BACKUP_ROOT=/var/lib/top40-archiver/backups/charly-install
EXPECTED_TGZ_SHA=e11271203dce95c49cc8c68d62135a42afe505bf3995df703139b22572a16fea
TMP=""
BACKUP=""
PREV_CORE_ACTIVE=0
PREV_GATEWAY_ACTIVE=0
PREV_OLLAMA_ACTIVE=0

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit." >&2; exit 1; }
[ -d "$VENDOR" ] || { echo "FOUT: CHARLY vendor-map ontbreekt: $VENDOR" >&2; exit 1; }
command -v base64 >/dev/null
command -v sha256sum >/dev/null
command -v tar >/dev/null
command -v tr >/dev/null
command -v systemctl >/dev/null
command -v curl >/dev/null

TMP=$(mktemp -d /tmp/top40-charly-install.XXXXXX)
BACKUP="$BACKUP_ROOT/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP"
chmod 0700 "$BACKUP"

systemctl is-active --quiet charly-core.service 2>/dev/null && PREV_CORE_ACTIVE=1 || true
systemctl is-active --quiet charly-ollama-gateway.service 2>/dev/null && PREV_GATEWAY_ACTIVE=1 || true
systemctl is-active --quiet ollama.service 2>/dev/null && PREV_OLLAMA_ACTIVE=1 || true

backup_tree() {
  local src=$1 name=$2
  if [ -e "$src" ]; then
    tar -C / -czf "$BACKUP/$name.tar.gz" "${src#/}"
  fi
}

backup_file() {
  local src=$1 name=$2
  if [ -e "$src" ]; then
    cp -a "$src" "$BACKUP/$name"
  fi
}

backup_tree /opt/charly opt-charly
backup_tree /etc/charly etc-charly
backup_file /etc/systemd/system/ollama.service.d/charly-backend.conf ollama-charly-backend.conf
backup_file /etc/systemd/system/charly-core.service charly-core.service
backup_file /etc/systemd/system/charly-ollama-gateway.service charly-ollama-gateway.service
backup_file /etc/systemd/system/charly-voice.service charly-voice.service
backup_file /etc/systemd/system/charly-face.service charly-face.service
backup_file /etc/sudoers.d/charly sudoers-charly
backup_file /usr/local/libexec/charly-systemctl charly-systemctl
backup_file /usr/local/bin/charly-ai charly-ai

cat >"$BACKUP/state.env" <<EOF
PREV_CORE_ACTIVE=$PREV_CORE_ACTIVE
PREV_GATEWAY_ACTIVE=$PREV_GATEWAY_ACTIVE
PREV_OLLAMA_ACTIVE=$PREV_OLLAMA_ACTIVE
EOF

restore_file_or_remove() {
  local backup=$1 target=$2
  if [ -e "$BACKUP/$backup" ]; then
    mkdir -p "$(dirname "$target")"
    cp -a "$BACKUP/$backup" "$target"
  else
    rm -f "$target"
  fi
}

rollback() {
  local rc=$?
  trap - ERR
  echo "CHARLY-integratie mislukt; vorige CHARLY/Ollama-configuratie wordt hersteld." >&2

  systemctl disable --now charly-ollama-gateway.service charly-core.service 2>/dev/null || true

  if [ -f "$BACKUP/opt-charly.tar.gz" ]; then
    rm -rf /opt/charly
    tar -C / -xzf "$BACKUP/opt-charly.tar.gz" || true
  else
    rm -rf /opt/charly
  fi
  if [ -f "$BACKUP/etc-charly.tar.gz" ]; then
    rm -rf /etc/charly
    tar -C / -xzf "$BACKUP/etc-charly.tar.gz" || true
  else
    rm -rf /etc/charly
  fi

  restore_file_or_remove ollama-charly-backend.conf /etc/systemd/system/ollama.service.d/charly-backend.conf
  restore_file_or_remove charly-core.service /etc/systemd/system/charly-core.service
  restore_file_or_remove charly-ollama-gateway.service /etc/systemd/system/charly-ollama-gateway.service
  restore_file_or_remove charly-voice.service /etc/systemd/system/charly-voice.service
  restore_file_or_remove charly-face.service /etc/systemd/system/charly-face.service
  restore_file_or_remove sudoers-charly /etc/sudoers.d/charly
  restore_file_or_remove charly-systemctl /usr/local/libexec/charly-systemctl
  restore_file_or_remove charly-ai /usr/local/bin/charly-ai

  systemctl daemon-reload || true
  if systemctl list-unit-files --no-legend ollama.service 2>/dev/null | grep -q '^ollama.service'; then
    systemctl restart ollama.service || true
  fi
  [ "$PREV_CORE_ACTIVE" -eq 1 ] && systemctl start charly-core.service 2>/dev/null || true
  [ "$PREV_GATEWAY_ACTIVE" -eq 1 ] && systemctl start charly-ollama-gateway.service 2>/dev/null || true

  echo "Rollback-map: $BACKUP" >&2
  exit "$rc"
}

cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT
trap rollback ERR

parts=("$VENDOR"/part-*.b64)
[ "${#parts[@]}" -eq 8 ] || { echo "FOUT: verwacht 8 CHARLY bron-delen, gevonden ${#parts[@]}." >&2; exit 1; }

# Base64 is only the textual transport format. Ignore line wrapping/whitespace
# and validate the decoded release archive itself with its fixed SHA-256.
cat "${parts[@]}" | tr -d '[:space:]' > "$TMP/CHARLY_v0.2.0-src.tar.gz.b64"
base64 -d "$TMP/CHARLY_v0.2.0-src.tar.gz.b64" > "$TMP/CHARLY_v0.2.0-src.tar.gz"
printf '%s  %s\n' "$EXPECTED_TGZ_SHA" "$TMP/CHARLY_v0.2.0-src.tar.gz" | sha256sum -c -
tar -tzf "$TMP/CHARLY_v0.2.0-src.tar.gz" >/dev/null
tar -xzf "$TMP/CHARLY_v0.2.0-src.tar.gz" -C "$TMP"

CHARLY_SOURCE="$TMP/charly-v0.2"
[ -x "$CHARLY_SOURCE/scripts/install-debian.sh" ] || chmod +x "$CHARLY_SOURCE/scripts/install-debian.sh"
[ -f "$CHARLY_SOURCE/charly/agent.py" ] || { echo "FOUT: CHARLY agent ontbreekt in bronpakket." >&2; exit 1; }
[ -f "$CHARLY_SOURCE/charly/gateway.py" ] || { echo "FOUT: CHARLY Ollama-gateway ontbreekt in bronpakket." >&2; exit 1; }

bash "$CHARLY_SOURCE/scripts/install-debian.sh"

# Integration health: core, transparent gateway and private Ollama backend.
curl -fsS --max-time 8 http://127.0.0.1:8765/api/health >/dev/null
if systemctl list-unit-files --no-legend ollama.service 2>/dev/null | grep -q '^ollama.service'; then
  curl -fsS --max-time 8 http://127.0.0.1:11435/api/version >/dev/null
  curl -fsS --max-time 8 http://127.0.0.1:11434/api/version >/dev/null
  curl -fsS --max-time 8 http://127.0.0.1:11434/api/tags >/dev/null
fi

# Top40 AI Control Room must survive the gateway swap.
if systemctl list-unit-files --no-legend top40-archiver-ai.service 2>/dev/null | grep -q '^top40-archiver-ai.service'; then
  systemctl restart top40-archiver-ai.service
  for _ in $(seq 1 20); do
    curl -fsS --max-time 3 http://127.0.0.1:8041/healthz >/dev/null 2>&1 && break
    sleep 0.5
  done
  curl -fsS --max-time 8 http://127.0.0.1:8041/healthz >/dev/null
fi

cat >"$BACKUP/INSTALL_OK" <<EOF
installed_at=$(date -Is)
charly_version=0.2.0
top40_version=$(tr -d '[:space:]' < "$APP/VERSION" 2>/dev/null || echo unknown)
ollama_public=127.0.0.1:11434
ollama_backend=127.0.0.1:11435
audio_library_touched=false
EOF
chmod 0600 "$BACKUP/INSTALL_OK"

trap - ERR

echo "CHARLY v0.2.0 is native geïntegreerd met Top40Archiver."
echo "CHARLY core:      http://127.0.0.1:8765"
echo "AI gateway:       http://127.0.0.1:11434"
echo "Ollama backend:   http://127.0.0.1:11435"
echo "Rollback-backup:  $BACKUP"
