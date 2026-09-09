# Top40Archiver

[Nederlands](README.md) · [English](README.en.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

[![Tests](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml/badge.svg)](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Debian 13](https://img.shields.io/badge/Debian-13-red.svg)](https://www.debian.org/)

Top40Archiver bouwt op Debian automatisch een lokaal muziekarchief op uit de Nederlandse **Top 40 en Tipparade**. SQLite blijft de leidende administratie: een track die eenmaal succesvol is verwerkt, wordt niet opnieuw gedownload alleen omdat het audiobestand later is verplaatst of verwijderd.

**Huidige release: 1.16.23**

Vanaf 1.16.23 gebruikt de NUC **CHARLY — Conversational Home Assistant Running Locally for You** als centrale AI-orchestrator. Bestaande Qwen/Ollama-taken blijven werken, maar Qwen is voortaan een lokale uitvoerder onder CHARLY. CHARLY kan per taak lokaal, online, hybride of via een externe AI-resource werken.

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

AI-verwerking op de NUC loopt centraal via:

```text
Top40Archiver / AI workers / Operator Chat / overige NUC-services
                         ↓
                  CHARLY Gateway :11434
                         ↓
                    CHARLY Core
                 ↙         ↓         ↘
             lokaal      online     extern
              Qwen      web/data      AI
             :11435
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
- **CHARLY Core/API/gezicht op poort `8765`**;
- **CHARLY Ollama-compatible gateway op poort `11434`**;
- private lokale Ollama/Qwen-backend op poort `11435`;
- automatische AI-routing met lokale en optionele externe resources;
- automatische GitHub-updates met backup- en rollbackvoorzieningen;
- externe muziekopslag via Samba.

## Services en poorten

```text
8040  Top40Archiver hoofdapplicatie
8041  AI Control Room / Operator Chat
8042  lokale Log & AI Control service
8765  CHARLY Core / API / gezicht
11434 CHARLY Ollama-compatible AI gateway
11435 Ollama/Qwen private backend
```

Belangrijkste services:

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-ai.service --no-pager
systemctl status top40-download-manager.service --no-pager
systemctl status top40-log-reader.service --no-pager
systemctl status top40-archiver-cover-art.service --no-pager
systemctl status charly-core.service --no-pager
systemctl status charly-ollama-gateway.service --no-pager
systemctl status ollama.service --no-pager
```

Downloadmanager live volgen:

```bash
journalctl -u top40-download-manager.service -f
```

CHARLY live volgen:

```bash
journalctl -u charly-core.service -f
journalctl -u charly-ollama-gateway.service -f
```

## Opslag en database

Hoofddatabase:

```text
/var/lib/top40-archiver/top40.sqlite3
```

Top40 AI-memory:

```text
/var/lib/top40-archiver/ai_memory.sqlite
```

CHARLY runtime, geheugen en audit:

```text
/var/lib/charly
```

CHARLY-configuratie:

```text
/etc/charly
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

Na installatie van 1.16.23 is CHARLY beschikbaar op:

```text
http://<IP-VAN-DE-NUC>:8765
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

Release 1.16.23 bevat:

```text
scripts/install-1.16.23.sh
scripts/install-charly-top40.sh
```

De bestaande database, instellingen, historische voortgang en muziekopslag blijven onderdeel van het update-/rollbackcontract. De CHARLY-installer maakt daarnaast vóór de Ollama-poortmigratie een eigen rollbackkopie.

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

## AI Operations en CHARLY

De bestaande Top40Archiver AI-laag ondersteunt operationsdiagnose, servicebewaking, downloadanalyse, provideranalyse, chart freshness, coverbewaking, Operator Chat en begrensde herstelacties. Die domeinlogica en veiligheidsregels blijven bestaan.

CHARLY wordt daarboven de centrale AI-orchestrator. Bestaande calls naar `127.0.0.1:11434` blijven compatibel, maar inference wordt door CHARLY ontvangen. CHARLY kan daarna zelf bepalen of lokaal Qwen/Ollama, externe compute of een hybride route het meest geschikt is.

CHARLY kent de taakklassen `REALTIME`, `HIGH`, `NORMAL` en `BATCH`, zodat interactieve taken voorrang kunnen krijgen op achtergrondwerk. Externe providers zijn optioneel; zonder cloudcredentials blijft lokale Qwen/Ollama beschikbaar.

De AI heeft geen onbeperkte vrije shell. Harde veiligheidsgrenzen mogen niet autonoom worden versoepeld. Privacygevoelige inhoud blijft standaard lokaal en de hoofdapplicatie op poort `8040` moet beschikbaar blijven wanneer de AI-laag een probleem heeft.

Zie [docs/CHARLY.md](docs/CHARLY.md) voor de volledige architectuur.

## Automatische updates

De updater vergelijkt de lokaal geïnstalleerde commit met het ingestelde GitHub-updatekanaal en registreert update-state onder:

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

De CHARLY-integratietest controleert daarnaast de vendored releasehashes, de gereconstrueerde bronarchive, installer-shellsyntax, gatewaypoorten en rollback-/audiobeschermingscontracten.

## Documentatie

- [Architectuur](docs/ARCHITECTURE.md)
- [CHARLY AI Orchestrator](docs/CHARLY.md)
- [Updaten en Samba](docs/UPDATE_AND_SMB.md)
- [Release 1.16.23](docs/RELEASE-1.16.23.md)
- [Changelog](CHANGELOG.md)
- [Bijdragen](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Juridisch gebruik

Gebruik downloadfunctionaliteit alleen voor materiaal waarvoor je toestemming of een andere geldige juridische grondslag hebt. De gebruiker blijft verantwoordelijk voor naleving van auteursrecht en de voorwaarden van gebruikte diensten.

## Licentie

MIT — zie [LICENSE](LICENSE).
