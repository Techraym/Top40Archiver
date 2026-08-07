#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Voer dit script als root uit: su -"
  exit 1
fi

VENV_PYTHON="/opt/top40-archiver/venv/bin/python"
SYSTEM_CA="/etc/ssl/certs/ca-certificates.crt"
TARGET_DIR="/etc/top40-archiver"
TARGET_BUNDLE="$TARGET_DIR/top40-ca-bundle.pem"
TMP_DIR=$(mktemp -d /tmp/top40-ca.XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

DV_R36_SHA256="8C54C334B66BA4E426772AF4A3F9136C19A1AEC729FDB28C535C07A5A4EF22E0"
ROOT_R46_SHA256="7BB647A62AEEAC88BF257AA522D01FFEA395E0AB45C73F93F65654EC38F25A06"

for command in curl openssl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "FOUT: vereist commando ontbreekt: $command"
    exit 1
  fi
done

if [ ! -x "$VENV_PYTHON" ]; then
  echo "FOUT: Python-omgeving ontbreekt: $VENV_PYTHON"
  exit 1
fi
if [ ! -s "$SYSTEM_CA" ]; then
  echo "FOUT: Debian CA-bundle ontbreekt: $SYSTEM_CA"
  exit 1
fi

convert_to_pem() {
  local input="$1"
  local output="$2"

  if openssl x509 -in "$input" -noout >/dev/null 2>&1; then
    openssl x509 -in "$input" -out "$output"
    return 0
  fi

  if openssl x509 -inform DER -in "$input" -noout >/dev/null 2>&1; then
    openssl x509 -inform DER -in "$input" -out "$output"
    return 0
  fi

  return 1
}

certificate_fingerprint() {
  openssl x509 -in "$1" -noout -fingerprint -sha256 |
    awk -F= '{gsub(":", "", $2); print toupper($2)}'
}

download_pinned_certificate() {
  local label="$1"
  local expected="$2"
  local output="$3"
  shift 3

  local url raw pem actual
  raw="$TMP_DIR/${label}.download"
  pem="$TMP_DIR/${label}.candidate.pem"

  for url in "$@"; do
    echo "$label downloaden via: $url"
    rm -f "$raw" "$pem"

    if ! curl --fail --silent --show-error --location --retry 3 \
      --connect-timeout 15 --max-time 120 \
      "$url" -o "$raw"; then
      echo "Waarschuwing: download mislukt via $url"
      continue
    fi

    if ! convert_to_pem "$raw" "$pem"; then
      echo "Waarschuwing: antwoord via $url is geen PEM- of DER-certificaat."
      echo "Ontvangen bytes: $(wc -c < "$raw")"
      continue
    fi

    actual=$(certificate_fingerprint "$pem")
    if [ "$actual" != "$expected" ]; then
      echo "Waarschuwing: verkeerde SHA-256 voor $label."
      echo "Verwacht: $expected"
      echo "Ontvangen: $actual"
      continue
    fi

    cp "$pem" "$output"
    echo "$label gecontroleerd: $actual"
    return 0
  done

  echo "FOUT: geen geldige, vastgepinde download gevonden voor $label."
  return 1
}

download_pinned_certificate \
  "Sectigo-DV-R36" \
  "$DV_R36_SHA256" \
  "$TMP_DIR/dv-r36.pem" \
  "https://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt" \
  "http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"

download_pinned_certificate \
  "Sectigo-Root-R46" \
  "$ROOT_R46_SHA256" \
  "$TMP_DIR/root-r46.pem" \
  "https://secure.sectigo.com/products/download/cacert/SectigoPublicServerAuthenticationRootR46.crt" \
  "https://crt.sectigo.com/SectigoPublicServerAuthenticationRootR46.crt" \
  "http://crt.sectigo.com/SectigoPublicServerAuthenticationRootR46.crt"

DV_SUBJECT=$(openssl x509 -in "$TMP_DIR/dv-r36.pem" -noout -subject -nameopt RFC2253)
DV_ISSUER=$(openssl x509 -in "$TMP_DIR/dv-r36.pem" -noout -issuer -nameopt RFC2253)
ROOT_SUBJECT=$(openssl x509 -in "$TMP_DIR/root-r46.pem" -noout -subject -nameopt RFC2253)
ROOT_ISSUER=$(openssl x509 -in "$TMP_DIR/root-r46.pem" -noout -issuer -nameopt RFC2253)

case "$DV_SUBJECT" in
  *"CN=Sectigo Public Server Authentication CA DV R36"*) ;;
  *) echo "FOUT: onverwacht DV R36-subject: $DV_SUBJECT"; exit 1 ;;
esac
case "$DV_ISSUER" in
  *"CN=Sectigo Public Server Authentication Root R46"*) ;;
  *) echo "FOUT: onverwachte DV R36-issuer: $DV_ISSUER"; exit 1 ;;
esac
case "$ROOT_SUBJECT" in
  *"CN=Sectigo Public Server Authentication Root R46"*) ;;
  *) echo "FOUT: onverwacht R46-subject: $ROOT_SUBJECT"; exit 1 ;;
esac
case "$ROOT_ISSUER" in
  *"CN=Sectigo Public Server Authentication Root R46"*) ;;
  *) echo "FOUT: onverwachte R46-issuer: $ROOT_ISSUER"; exit 1 ;;
esac

echo "Certificaatketen cryptografisch controleren..."
openssl verify \
  -CAfile "$TMP_DIR/root-r46.pem" \
  "$TMP_DIR/dv-r36.pem"

mkdir -p "$TARGET_DIR"
cat "$SYSTEM_CA" \
    "$TMP_DIR/root-r46.pem" \
    "$TMP_DIR/dv-r36.pem" \
    > "$TARGET_BUNDLE"
chown root:root "$TARGET_BUNDLE"
chmod 644 "$TARGET_BUNDLE"

echo "HTTPS-verbinding met Top40.nl testen..."
TOP40_CA_BUNDLE="$TARGET_BUNDLE" "$VENV_PYTHON" - <<'PY'
import os
import requests

bundle = os.environ["TOP40_CA_BUNDLE"]
response = requests.get(
    "https://www.top40.nl/tipparade",
    timeout=30,
    verify=bundle,
    headers={"User-Agent": "Top40Archiver TLS-test"},
)
response.raise_for_status()
print(
    f"Top40.nl TLS-test geslaagd: HTTP {response.status_code}, "
    f"{len(response.content)} bytes"
)
PY

echo "Top40Archiver CA-bundle geïnstalleerd: $TARGET_BUNDLE"
