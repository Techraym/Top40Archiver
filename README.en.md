# Top40Archiver

[Nederlands](README.md) · [English](README.en.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

[![Tests](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml/badge.svg)](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Debian 13](https://img.shields.io/badge/Debian-13-red.svg)](https://www.debian.org/)

Top40Archiver automatically builds a local music archive on Debian from the Dutch **Top 40 and Tipparade**. SQLite remains the authoritative administration: once a track has been processed successfully, it is not downloaded again merely because the audio file was moved or removed later.

**Current release: 1.16.22**

## Core architecture

```text
Top 40 + Tipparade
        ↓
artist + title normalization
        ↓
SQLite deduplication
        ↓
optional metadata enrichment
        ↓
persistent download queue
        ↓
Multi Source Download Engine
        ↓
candidate matching + version checks
        ↓
FFprobe / FFmpeg validation
        ↓
final audio storage
        ↓
cover-art processing
```

The web application does not perform long-running external downloads itself. Download work is queued persistently and processed by the standalone download manager.

## Main features

- current Top 40 and Tipparade;
- historical Top 40 from `1965-W01`;
- historical Tipparade from `1967-W28`;
- resumable historical imports;
- automatic freshness checks for current charts;
- persistent central download queue;
- standalone `top40-download-manager.service`;
- dynamic, bounded download concurrency;
- provider-specific pacing, health, cooldowns and circuit breakers;
- extensive artist/title matching and version checks;
- protection against previews, karaoke, tribute, covers and unwanted alternate versions;
- FFprobe/FFmpeg validation before final storage;
- continuous album-cover worker;
- FastAPI main interface on port `8040`;
- AI Control Room and Operator functionality on port `8041`;
- local Log & AI Control service on port `8042`;
- local Ollama/Qwen integration for bounded diagnosis and management;
- automatic GitHub updates with backup and rollback support;
- external music storage through Samba.

## Services and ports

```text
8040  Top40Archiver main application
8041  AI Control Room / Operator Chat
8042  local Log & AI Control service
11434 Ollama, local only
```

Main services:

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-ai.service --no-pager
systemctl status top40-download-manager.service --no-pager
systemctl status top40-log-reader.service --no-pager
systemctl status top40-archiver-cover-art.service --no-pager
systemctl status ollama.service --no-pager
```

Follow the download manager live:

```bash
journalctl -u top40-download-manager.service -f
```

## Storage and databases

Main database:

```text
/var/lib/top40-archiver/top40.sqlite3
```

AI memory:

```text
/var/lib/top40-archiver/ai_memory.sqlite
```

Temporary download files:

```text
/var/lib/top40-archiver/download-temp
```

Default music storage:

```text
/mnt/top40-music/Top40
```

Example:

```text
/mnt/top40-music/Top40/Pop/A/Adele - Hello.mp3
```

## Fresh installation on Debian 13

```bash
git clone https://github.com/Techraym/Top40Archiver.git
cd Top40Archiver
chmod +x install.sh update-existing.sh update-from-github.sh auto-update.sh setup-network-share.sh update-timer.sh
su -c ./install.sh
```

Then open:

```text
http://<NUC-IP>:8040
```

## Updating an existing installation

```bash
su -
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh
chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

Release 1.16.22 also includes:

```text
scripts/install-1.16.22.sh
```

The existing database, settings, historical progress and music storage remain part of the update/rollback contract.

## Download policy

Top40Archiver uses a Multi Source Download Engine with controlled provider paths. Candidates are evaluated by identity and available metadata and are technically validated before final storage.

Important safety boundaries:

- existing audio is not deleted autonomously;
- existing audio is not silently overwritten;
- no CAPTCHA bypass;
- no personal account or cookie automation as a workaround;
- no proxy rotation to evade blocking;
- no rate-limit bypass;
- candidate matching and audio validation remain mandatory.

## AI Operations

The local AI layer supports operations diagnosis, service monitoring, download analysis, provider analysis, chart freshness, cover monitoring, Operator Chat and bounded recovery actions.

The AI has no unrestricted free shell. Hard safety boundaries may not be weakened autonomously. The main application on port `8040` must remain available if the AI layer encounters a problem.

## Automatic updates

The updater compares the locally installed commit with GitHub `main` and stores update state under:

```text
/var/lib/top40-archiver/update-state/
```

Status:

```bash
systemctl status top40-archiver-auto-update.timer --no-pager
journalctl -u top40-archiver-auto-update.service -n 100 --no-pager
```

Force a check/reinstallation:

```bash
/opt/top40-archiver/auto-update.sh --force
```

## Samba

Check the external storage first:

```bash
findmnt /mnt/top40-music
runuser -u top40archiver -- test -w /mnt/top40-music && echo "Writable"
```

Configure:

```bash
/opt/top40-archiver/setup-network-share.sh
```

Windows path:

```text
\\Top40\Top40Music
```

## Testing

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
pytest
```

Release **1.16.22** was validated with **257 passing tests** and a Python syntax check with no errors.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Updates and Samba](docs/UPDATE_AND_SMB.md)
- [Release 1.16.22](docs/RELEASE-1.16.22.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Legal use

Use download functionality only for material for which you have permission or another valid legal basis. The user remains responsible for compliance with copyright law and the terms of the services used.

## License

MIT — see [LICENSE](LICENSE).
