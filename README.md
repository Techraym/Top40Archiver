# Top40Archiver

[![Tests](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml/badge.svg)](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Debian 13](https://img.shields.io/badge/Debian-13-red.svg)](https://www.debian.org/)

Top40Archiver bouwt op Debian automatisch een lokaal muziekarchief op uit de Nederlandse **Top 40 en Tipparade**. SQLite bepaalt permanent welke nummers al zijn verwerkt; alleen werkelijk nieuwe nummers worden gedownload.

## Kernwerking

```text
Top 40 + Tipparade ophalen
→ artiest en titel normaliseren
→ vergelijken met SQLite
→ Spotify gebruiken als metadata-controle
→ passende YouTube-versie zoeken
→ als MP3 downloaden
→ opslaan per genre en beginteken
→ permanent registreren in SQLite
```

Een nummer dat eerst in de Tipparade staat en later in de Top 40 komt, wordt niet opnieuw gedownload. Een MP3 die later van de externe schijf wordt verwijderd, wordt evenmin opnieuw gedownload wanneer SQLite al status `downloaded` bevat.

## Functies

- actuele Top 40 en Tipparade;
- historische Top 40 vanaf `1965-W01`;
- historische Tipparade vanaf `1967-W28`;
- hervatbare historische batches;
- automatische overgang naar wekelijkse actuele controles;
- Spotify uitsluitend voor metadata, nooit voor audio;
- YouTube-download via yt-dlp en FFmpeg;
- live FastAPI-dashboard op poort `8040`;
- systemd-services en timers;
- externe USB-C-opslag als Windows-netwerkschijf via Samba;
- opslag als `Genre/beginletter/Artiest - Titel.mp3`.

## Opslag en database

Database op de interne systeemschijf:

```text
/var/lib/top40-archiver/top40.sqlite3
```

Standaard downloadmap:

```text
/mnt/top40-music/Top40
```

Voorbeeld:

```text
/mnt/top40-music/Top40/Pop/A/Adele - Hello.mp3
/mnt/top40-music/Top40/Dance/2/2 Unlimited - No Limit.mp3
/mnt/top40-music/Top40/Rock/#/#1 Dads - So Soldier.mp3
```

## Nieuwe installatie op Debian 13

```bash
git clone https://github.com/Techraym/Top40Archiver.git
cd Top40Archiver
chmod +x install.sh update-existing.sh update-from-github.sh setup-network-share.sh update-timer.sh
su -c ./install.sh
```

Open daarna:

```text
http://<IP-VAN-DE-NUC>:8040
```

## Bestaande installatie updaten vanaf GitHub

```bash
su -
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh
chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

De bestaande database, instellingen, historische voortgang en downloadstatussen blijven behouden.

## Spotify als controle instellen

```bash
nano /etc/top40-archiver.env
```

```text
SPOTIFY_CLIENT_ID=jouw_client_id
SPOTIFY_CLIENT_SECRET=jouw_client_secret
SPOTIFY_MARKET=NL
```

Daarna:

```bash
systemctl restart top40-archiver-web.service
```

## Externe opslag delen met Windows

De externe schijf moet eerst gekoppeld en schrijfbaar zijn op `/mnt/top40-music`.

```bash
findmnt /mnt/top40-music
runuser -u top40archiver -- test -w /mnt/top40-music && echo "Schrijven werkt"
/opt/top40-archiver/setup-network-share.sh
```

Windows-pad:

```text
\\Top40\Top40Music
```

of:

```text
\\<IP-VAN-DE-NUC>\Top40Music
```

Gebruik Linux-/Samba-gebruiker `top40`. Zie [de volledige update- en Samba-instructie](docs/UPDATE_AND_SMB.md).

## Diensten en logs

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-check.timer --no-pager
systemctl status top40-archiver-history.timer --no-pager
systemctl status smbd.service --no-pager
```

Actuele controle:

```bash
systemctl start top40-archiver-check.service
journalctl -u top40-archiver-check.service -f
```

Historische batch:

```bash
systemctl start top40-archiver-history.service
journalctl -u top40-archiver-history.service -f
```

## Ontwikkelen en testen

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
pytest
```

## Documentatie

- [Architectuur](docs/ARCHITECTURE.md)
- [Updaten en Samba](docs/UPDATE_AND_SMB.md)
- [Changelog](CHANGELOG.md)
- [Bijdragen](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Juridisch gebruik

Gebruik downloadfunctionaliteit alleen voor materiaal waarvoor je toestemming of een andere geldige juridische grondslag hebt. De gebruiker blijft verantwoordelijk voor naleving van auteursrecht en de voorwaarden van de gebruikte diensten.

## Licentie

MIT — zie [LICENSE](LICENSE).
