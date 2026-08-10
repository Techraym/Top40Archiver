# Top40Archiver

[Nederlands](README.md) · [English](README.en.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

[![Tests](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml/badge.svg)](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Debian 13](https://img.shields.io/badge/Debian-13-red.svg)](https://www.debian.org/)

Top40Archiver erstellt unter Debian automatisch ein lokales Musikarchiv aus der niederländischen **Top 40 und Tipparade**. SQLite bleibt die führende Verwaltung: Ein Titel, der einmal erfolgreich verarbeitet wurde, wird nicht allein deshalb erneut heruntergeladen, weil die Audiodatei später verschoben oder entfernt wurde.

**Aktuelle Version: 1.16.22**

## Kernarchitektur

```text
Top 40 + Tipparade
        ↓
Normalisierung von Künstler + Titel
        ↓
SQLite-Deduplizierung
        ↓
optionale Metadaten-Anreicherung
        ↓
persistente Download-Warteschlange
        ↓
Multi Source Download Engine
        ↓
Kandidatenabgleich + Versionsprüfung
        ↓
FFprobe / FFmpeg-Validierung
        ↓
endgültige Audiospeicherung
        ↓
Cover-Art-Verarbeitung
```

Die Webanwendung führt lang laufende externe Downloads nicht selbst aus. Download-Aufgaben werden persistent eingereiht und vom eigenständigen Download-Manager verarbeitet.

## Wichtigste Funktionen

- aktuelle Top 40 und Tipparade;
- historische Top 40 ab `1965-W01`;
- historische Tipparade ab `1967-W28`;
- fortsetzbare historische Importe;
- automatische Aktualitätsprüfung der aktuellen Charts;
- persistente zentrale Download-Warteschlange;
- eigenständiger `top40-download-manager.service`;
- dynamische, begrenzte Download-Parallelität;
- provider-spezifisches Pacing, Health, Cooldowns und Circuit Breaker;
- umfangreicher Künstler-/Titelabgleich und Versionsprüfung;
- Schutz vor Previews, Karaoke, Tribute, Covers und unerwünschten Alternativversionen;
- FFprobe/FFmpeg-Validierung vor der endgültigen Speicherung;
- kontinuierlicher Albumcover-Worker;
- FastAPI-Hauptoberfläche auf Port `8040`;
- AI Control Room und Operator-Funktionen auf Port `8041`;
- lokaler Log-&-AI-Control-Dienst auf Port `8042`;
- lokale Ollama/Qwen-Integration für begrenzte Diagnose und Verwaltung;
- automatische GitHub-Updates mit Backup- und Rollback-Unterstützung;
- externer Musikspeicher über Samba.

## Dienste und Ports

```text
8040  Top40Archiver-Hauptanwendung
8041  AI Control Room / Operator Chat
8042  lokaler Log & AI Control-Dienst
11434 Ollama, lokal
```

Wichtigste Dienste:

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-ai.service --no-pager
systemctl status top40-download-manager.service --no-pager
systemctl status top40-log-reader.service --no-pager
systemctl status top40-archiver-cover-art.service --no-pager
systemctl status ollama.service --no-pager
```

Download-Manager live verfolgen:

```bash
journalctl -u top40-download-manager.service -f
```

## Speicher und Datenbanken

Hauptdatenbank:

```text
/var/lib/top40-archiver/top40.sqlite3
```

AI-Memory:

```text
/var/lib/top40-archiver/ai_memory.sqlite
```

Temporäre Download-Dateien:

```text
/var/lib/top40-archiver/download-temp
```

Standard-Musikspeicher:

```text
/mnt/top40-music/Top40
```

Beispiel:

```text
/mnt/top40-music/Top40/Pop/A/Adele - Hello.mp3
```

## Neuinstallation auf Debian 13

```bash
git clone https://github.com/Techraym/Top40Archiver.git
cd Top40Archiver
chmod +x install.sh update-existing.sh update-from-github.sh auto-update.sh setup-network-share.sh update-timer.sh
su -c ./install.sh
```

Danach öffnen:

```text
http://<NUC-IP>:8040
```

## Bestehende Installation aktualisieren

```bash
su -
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh
chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

Release 1.16.22 enthält außerdem:

```text
scripts/install-1.16.22.sh
```

Die bestehende Datenbank, Einstellungen, historische Fortschritte und Musikspeicher bleiben Bestandteil des Update-/Rollback-Vertrags.

## Download-Richtlinie

Top40Archiver verwendet eine Multi Source Download Engine mit kontrollierten Provider-Pfaden. Kandidaten werden anhand ihrer Identität und verfügbarer Metadaten bewertet und vor der endgültigen Speicherung technisch validiert.

Wichtige Sicherheitsgrenzen:

- vorhandene Audiodateien werden nicht autonom gelöscht;
- vorhandene Audiodateien werden nicht stillschweigend überschrieben;
- kein CAPTCHA-Bypass;
- keine Automatisierung persönlicher Konten oder Cookies als Workaround;
- keine Proxyrotation zur Umgehung von Sperren;
- kein Rate-Limit-Bypass;
- Kandidatenabgleich und Audiovalidierung bleiben verpflichtend.

## AI Operations

Die lokale AI-Schicht unterstützt unter anderem Operations-Diagnose, Dienstüberwachung, Downloadanalyse, Provideranalyse, Chart-Freshness, Cover-Überwachung, Operator Chat und begrenzte Wiederherstellungsaktionen.

Die AI besitzt keine unbegrenzte freie Shell. Harte Sicherheitsgrenzen dürfen nicht autonom gelockert werden. Die Hauptanwendung auf Port `8040` muss verfügbar bleiben, wenn die AI-Schicht ein Problem hat.

## Automatische Updates

Der Updater vergleicht den lokal installierten Commit mit GitHub `main` und speichert den Update-Status unter:

```text
/var/lib/top40-archiver/update-state/
```

Status:

```bash
systemctl status top40-archiver-auto-update.timer --no-pager
journalctl -u top40-archiver-auto-update.service -n 100 --no-pager
```

Prüfung/Neuinstallation erzwingen:

```bash
/opt/top40-archiver/auto-update.sh --force
```

## Samba

Zuerst den externen Speicher prüfen:

```bash
findmnt /mnt/top40-music
runuser -u top40archiver -- test -w /mnt/top40-music && echo "Schreibbar"
```

Konfigurieren:

```bash
/opt/top40-archiver/setup-network-share.sh
```

Windows-Pfad:

```text
\\Top40\Top40Music
```

## Testen

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
pytest
```

Release **1.16.22** wurde mit **257 erfolgreichen Tests** und einer Python-Syntaxprüfung ohne Fehler validiert.

## Dokumentation

- [Architektur](docs/ARCHITECTURE.md)
- [Updates und Samba](docs/UPDATE_AND_SMB.md)
- [Release 1.16.22](docs/RELEASE-1.16.22.md)
- [Changelog](CHANGELOG.md)
- [Mitwirken](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Rechtliche Nutzung

Verwende die Download-Funktion nur für Material, für das eine Erlaubnis oder eine andere gültige Rechtsgrundlage besteht. Der Benutzer bleibt für die Einhaltung des Urheberrechts und der Bedingungen der verwendeten Dienste verantwortlich.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
