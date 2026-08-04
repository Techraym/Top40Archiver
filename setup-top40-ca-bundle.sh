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

DV_R36_URL="https://crt.sh/?d=4267304690"
R46_CROSS_URL="https://crt.sh/?d=11405654893"

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

echo "Sectigo DV R36-certificaat downloaden..."
curl --fail --silent --show-error --location --retry 3 \
  --connect-timeout 15 --max-time 120 \
  "$DV_R36_URL" -o "$TMP_DIR/dv-r36.der"

echo "Sectigo R46 x USERTrust-certificaat downloaden..."
curl --fail --silent --show-error --location --retry 3 \
  --connect-timeout 15 --max-time 120 \
  "$R46_CROSS_URL" -o "$TMP_DIR/r46-usertrust.der"

openssl x509 -inform DER -in "$TMP_DIR/dv-r36.der" -out "$TMP_DIR/dv-r36.pem"
openssl x509 -inform DER -in "$TMP_DIR/r46-usertrust.der" -out "$TMP_DIR/r46-usertrust.pem"

DV_SUBJECT=$(openssl x509 -in "$TMP_DIR/dv-r36.pem" -noout -subject -nameopt RFC2253)
DV_ISSUER=$(openssl x509 -in "$TMP_DIR/dv-r36.pem" -noout -issuer -nameopt RFC2253)
R46_SUBJECT=$(openssl x509 -in "$TMP_DIR/r46-usertrust.pem" -noout -subject -nameopt RFC2253)
R46_ISSUER=$(openssl x509 -in "$TMP_DIR/r46-usertrust.pem" -noout -issuer -nameopt RFC2253)

case "$DV_SUBJECT" in
  *"CN=Sectigo Public Server Authentication CA DV R36"*) ;;
  *) echo "FOUT: onverwacht DV R36-subject: $DV_SUBJECT"; exit 1 ;;
esac
case "$DV_ISSUER" in
  *"CN=Sectigo Public Server Authentication Root R46"*) ;;
  *) echo "FOUT: onverwachte DV R36-issuer: $DV_ISSUER"; exit 1 ;;
esac
case "$R46_SUBJECT" in
  *"CN=Sectigo Public Server Authentication Root R46"*) ;;
  *) echo "FOUT: onverwacht R46-subject: $R46_SUBJECT"; exit 1 ;;
esac
case "$R46_ISSUER" in
  *"CN=USERTrust RSA Certification Authority"*) ;;
  *) echo "FOUT: onverwachte R46-issuer: $R46_ISSUER"; exit 1 ;;
esac

echo "Certificaatketen cryptografisch controleren..."
openssl verify \
  -CAfile "$SYSTEM_CA" \
  -untrusted "$TMP_DIR/r46-usertrust.pem" \
  "$TMP_DIR/dv-r36.pem"

mkdir -p "$TARGET_DIR"
cat "$SYSTEM_CA" \
    "$TMP_DIR/r46-usertrust.pem" \
    "$TMP_DIR/dv-r36.pem" \
    > "$TARGET_BUNDLE"
chown root:root "$TARGET_BUNDLE"
chmod 644 "$TARGET_BUNDLE"

CERTIFI_PATH=$(
  "$VENV_PYTHON" -c 'import certifi; print(certifi.where())'
)
if [ ! -f "$CERTIFI_PATH" ]; then
  echo "FOUT: certifi-bundle niet gevonden: $CERTIFI_PATH"
  exit 1
fi

if [ ! -f "${CERTIFI_PATH}.top40-upstream" ]; then
  cp -a "$CERTIFI_PATH" "${CERTIFI_PATH}.top40-upstream"
fi
cp "$TARGET_BUNDLE" "$CERTIFI_PATH"
chown root:root "$CERTIFI_PATH"
chmod 644 "$CERTIFI_PATH"

echo "HTTPS-verbinding met Top40.nl testen..."
"$VENV_PYTHON" - <<'PY'
import certifi
import requests

response = requests.get(
    "https://www.top40.nl/tipparade",
    timeout=30,
    verify=certifi.where(),
    headers={"User-Agent": "Top40Archiver TLS-test"},
)
response.raise_for_status()
print(f"Top40.nl TLS-test geslaagd: HTTP {response.status_code}, {len(response.content)} bytes")
PY

echo "Top40Archiver CA-bundle geïnstalleerd: $TARGET_BUNDLE"
