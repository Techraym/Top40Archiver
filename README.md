# Top40Archiver

[Nederlands](README.md) · [English](README.en.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

[![Tests](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml/badge.svg)](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Debian 13](https://img.shields.io/badge/Debian-13-red.svg)](https://www.debian.org/)

Top40Archiver bouwt op Debian automatisch een lokaal muziekarchief op uit de Nederlandse **Top 40 en Tipparade**. SQLite blijft de leidende administratie: een track die eenmaal succesvol is verwerkt, wordt niet opnieuw gedownload alleen omdat het audiobestand later is verplaatst of verwijderd.

**Huidige release: 1.16.22**

## Kernarchitectuur

```text
Top 40 + Tipparade
        ↓
normalisatie artiest + titel
        ↓
SQLite-deduplicatie
        ↓
optionele metadata-verrijking
        ↓
persistente downloadqueue
        ↓
Multi Source Download Engine
        ↓
kandidaatmatching + versiecontrole
        ↓
FFprobe / FFmpeg-validatie
        ↓
definitieve audio-opslag
        ↓
cover-art verwerking
```

De webapplicatie voert langdurige externe downloads niet zelf uit. Downloadwerk wordt persistent gequeued en verwerkt door de zelfstandige downloadmanager.

## Belangrijkste functies

- actuele Top 40 en Tipparade;
- historische Top 40 vanaf `1965-W01`;
- historische Tipparade vanaf `1967-W28`;
- hervatbare historische imports;
- automatische freshness-controle van actuele hitlijsten;
- persistente centrale downloadqueue;
- zelfstandige `top40-download-manager.service`;
- dynamische, begrensde downloadconcurrency;
- provider-specifieke pacing, health, cooldowns en circuit breakers;
- uitgebreide artiest-/titelmatching en versiecontrole;
- bescherming tegen previews, karaoke, tribute, covers en ongewenste alternatieve versies;
- FFprobe/FFmpeg-validatie vóór definitieve opslag;
- continue albumcover-worker;
- FastAPI-hoofdinterface op poort `8040`;
- AI Control Room en Operator-functionaliteit op poort `8041`;
- lokale Log & AI Control service op poort `8042`;
- lokale Ollama/Qwen-integratie voor begrensde diagnose en beheer;
- automatische GitHub-updates met backup- en rollbackvoorzieningen;
- externe muziekopslag via Samba.

## Services en poorten

```text
8040  Top40Archiver hoofdapplicatie
8041  AI Control Room / Operator Chat
8042  lokale Log & AI Control service
11434 Ollama, lokaal
```

Belangrijkste services:

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-ai.service --no-pager
systemctl status top40-download-manager.service --no-pager
systemctl status top40-log-reader.service --no-pager
systemctl status top40-archiver-cover-art.service --no-pager
systemctl status ollama.service --no-pager
```

Downloadmanager live volgen:

```bash
journalctl -u top40-download-manager.service -f
```

## Opslag en database

Hoofddatabase:

```text
/var/lib/top40-archiver/top40.sqlite3
```

AI-memory:

```text
/var/lib/top40-archiver/ai_memory.sqlite
```

Tijdelijke downloadbestanden:

```text
/var/lib/top40-archiver/download-temp
```

Standaard muziekopslag:

```text
/mnt/top40-music/Top40
```

Voorbeeld:

```text
/mnt/top40-music/Top40/Pop/A/Adele - Hello.mp3
```

## Nieuwe installatie op Debian 13

```bash
git clone https://github.com/Techraym/Top40Archiver.git
cd Top40Archiver
chmod +x install.sh update-existing.sh update-from-github.sh auto-update.sh setup-network-share.sh update-timer.sh
su -c ./install.sh
```

Open daarna:

```text
http://<IP-VAN-DE-NUC>:8040
```

## Bestaande installatie updaten

```bash
su -
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh
chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

Release 1.16.22 bevat tevens:

```text
scripts/install-1.16.22.sh
```

De bestaande database, instellingen, historische voortgang en muziekopslag blijven onderdeel van het update-/rollbackcontract.

## Downloadbeleid

Top40Archiver gebruikt een Multi Source Download Engine met gecontroleerde providerpaden. Kandidaten worden beoordeeld op identiteit en beschikbare metadata en technisch gevalideerd voordat ze definitief worden opgeslagen.

Belangrijke veiligheidsgrenzen:

- bestaande audio wordt niet autonoom verwijderd;
- bestaande audio wordt niet stilzwijgend overschreven;
- geen CAPTCHA-bypass;
- geen account- of persoonlijke cookie-automatisering als workaround;
- geen proxyrotatie om blokkades te omzeilen;
- geen rate-limit-bypass;
- kandidaatmatching en audiovalidatie blijven verplicht.

## AI Operations

De lokale AI-laag ondersteunt onder andere operationsdiagnose, servicebewaking, downloadanalyse, provideranalyse, chart freshness, coverbewaking, Operator Chat en begrensde herstelacties.

De AI heeft geen onbeperkte vrije shell. Harde veiligheidsgrenzen mogen niet autonoom worden versoepeld. De hoofdapplicatie op poort `8040` moet beschikbaar blijven wanneer de AI-laag een probleem heeft.

## Automatische updates

De updater vergelijkt de lokaal geïnstalleerde commit met GitHub `main` en registreert update-state onder:

```text
/var/lib/top40-archiver/update-state/
```

Status:

```bash
systemctl status top40-archiver-auto-update.timer --no-pager
journalctl -u top40-archiver-auto-update.service -n 100 --no-pager
```

Geforceerd controleren/herinstalleren:

```bash
/opt/top40-archiver/auto-update.sh --force
```

## Samba

Controleer eerst de externe opslag:

```bash
findmnt /mnt/top40-music
runuser -u top40archiver -- test -w /mnt/top40-music && echo "Schrijven werkt"
```

Configureren:

```bash
/opt/top40-archiver/setup-network-share.sh
```

Windows-pad:

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

Release **1.16.22** is gevalideerd met **257 geslaagde tests** en een Python-syntaxcontrole zonder fouten.

## Documentatie

- [Architectuur](docs/ARCHITECTURE.md)
- [Updaten en Samba](docs/UPDATE_AND_SMB.md)
- [Release 1.16.22](docs/RELEASE-1.16.22.md)
- [Changelog](CHANGELOG.md)
- [Bijdragen](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Juridisch gebruik

Gebruik downloadfunctionaliteit alleen voor materiaal waarvoor je toestemming of een andere geldige juridische grondslag hebt. De gebruiker blijft verantwoordelijk voor naleving van auteursrecht en de voorwaarden van gebruikte diensten.

## Licentie

MIT — zie [LICENSE](LICENSE).
