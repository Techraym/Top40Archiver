# CHARLY — centrale AI-orchestrator op de NUC

CHARLY staat voor **Conversational Home Assistant Running Locally for You**.

Vanaf Top40Archiver 1.16.23 wordt CHARLY native op dezelfde Debian NUC geïnstalleerd en vormt hij de centrale AI-laag voor de bestaande en toekomstige AI-taken. Qwen/Ollama blijft beschikbaar, maar is voortaan een uitvoerend lokaal model onder CHARLY en niet langer de centrale AI-interface.

## Architectuur

```text
Top40Archiver / AI workers / Operator Chat / overige NUC-services
                         │
                         │ Ollama-compatible API
                         ▼
                127.0.0.1:11434
                  CHARLY Gateway
                         │
             ┌───────────┴───────────┐
             │                       │
             ▼                       ▼
        CHARLY Core             modelbeheer
      127.0.0.1:8765                 │
             │                       ▼
             │                Ollama backend
             │               127.0.0.1:11435
             │
      ┌──────┼───────────────┐
      │      │               │
      ▼      ▼               ▼
    LOCAL  ONLINE         DELEGATE
    Qwen   web/data       externe AI
      └──────────┬───────────┘
                 ▼
              resultaat
```

Bestaande software die `http://127.0.0.1:11434/api/generate` of `/api/chat` gebruikt hoeft daardoor niet direct te worden herschreven. Inference gaat via CHARLY. Niet-inference Ollama-endpoints, zoals modelbeheer en `/api/tags`, worden door de gateway naar de private Ollama-backend op poort 11435 doorgestuurd.

## Routing

CHARLY kiest per taak zelf de uitvoeringsroute. De gebruiker hoeft niet aan te geven of iets lokaal of online moet gebeuren.

- **LOCAL** — lokale verwerking, onder andere voor privacygevoelige informatie en offline fallback.
- **ONLINE** — actuele informatie of webbronnen zijn nodig.
- **HYBRID** — lokale systeemdata wordt gecombineerd met externe informatie of rekenkracht.
- **DELEGATE** — zware of specialistische taken worden naar een geschikte externe resource gestuurd.

De router kijkt onder andere naar actualiteit, privacy, taakcomplexiteit, beschikbare lokale capaciteit, verwachte kwaliteit en snelheid. Externe providers zijn optioneel. Zonder cloudcredentials blijft CHARLY via lokaal Ollama/Qwen functioneren.

## Prioriteiten

CHARLY heeft een centrale taakqueue met vier klassen:

```text
REALTIME  gesproken/interactieve taken
HIGH      actieve diagnose en urgente systeemtaken
NORMAL    normale machine-AI taken
BATCH     backfills, verrijking en ander achtergrondwerk
```

Hierdoor hoeft een interactieve vraag niet achter omvangrijk achtergrondwerk te wachten. De bestaande Top40Archiver-policy rond operatorprioriteit, veilige herstelacties, backups en rollback blijft daarnaast actief.

## Natuurlijke taal en agentgedrag

Voor gesprekken met CHARLY zijn geen vaste gesproken commando's bedoeld. De menselijke interface gebruikt natuurlijke taal, gesprekcontext en vervolgvragen. Intern blijven acties juist strikt gedefinieerde tools/functies.

CHARLY kan bij een doelgerichte opdracht:

1. het doel interpreteren;
2. een plan vormen;
3. lokaal bewijs verzamelen;
4. geschikte tools en AI-resources kiezen;
5. acties uitvoeren binnen de toegestane grenzen;
6. het resultaat controleren;
7. zo nodig een vervolgstap proberen;
8. natuurlijk terugkoppelen.

CHARLY is daarmee agentisch in functionele zin, niet bewust of zelfbewust.

## Veiligheidsgrenzen

De komst van CHARLY verruimt de bestaande harde Top40Archiver-veiligheidsgrenzen niet.

- geen onbeperkte vrije shell voor het model;
- systeemacties lopen via allowlists en geaudite helpers;
- bestaande audio wordt niet autonoom verwijderd of overschreven;
- CAPTCHA-, rate-limit- en proxy-bypass blijven verboden;
- vertrouwelijke/sensitieve data gaat standaard niet naar externe AI;
- impactvolle acties kunnen strengere rechten of menselijke toestemming vereisen;
- iedere machine-AI taak kan in CHARLY's audit- en taskdatabase worden vastgelegd.

## Native installatie

CHARLY gebruikt geen Docker en geen aparte VM.

```text
/opt/charly          applicatie en virtuele Python-omgeving
/etc/charly          configuratie en providerinstellingen
/var/lib/charly      geheugen, taken, auditdata en runtime-data
```

Belangrijke services:

```text
charly-core.service
charly-ollama-gateway.service
charly-voice.service           optioneel
charly-face.service            optioneel
```

Belangrijke poorten:

```text
8765   CHARLY Core API + gezicht
11434  CHARLY Ollama-compatible gateway
11435  private Ollama/Qwen backend
8041   Top40Archiver AI Control Room
```

## Externe AI

Providerinstellingen staan onder:

```text
/etc/charly/providers.json
/etc/charly/charly.env
```

CHARLY is model-onafhankelijk. Qwen is één mogelijke lokale provider; snelle cloudmodellen, reasoningmodellen en specialistische diensten kunnen later worden toegevoegd zonder de identiteit, het geheugen of de Top40Archiver-integratie te vervangen.

## Gezicht en spraak

De core serveert een HDMI/browsergeschikt gezicht via poort 8765. De optionele voice-service verzorgt wake-word/spraakherkenning en TTS. Deze onderdelen staan los van de machine-AI gateway: Top40Archiver blijft dus ook functioneren wanneer geen scherm, microfoon of speaker is aangesloten.

## Installatie en rollback

`scripts/install-charly-top40.sh` reconstrueert de gecontroleerde CHARLY v0.2.0 bronrelease uit `vendor/charly-v0.2.0`, valideert SHA-256, maakt een rollbackkopie en voert daarna de native installer uit.

Tijdens de gatewaymigratie verhuist Ollama van `127.0.0.1:11434` naar `127.0.0.1:11435`. Pas nadat de private backend gezond is neemt CHARLY poort 11434 over. Na installatie worden de CHARLY-core, gateway, Ollama-backend en Top40Archiver AI Control Room gecontroleerd.

Bij een fout wordt de eerdere CHARLY/Ollama-configuratie teruggezet. De muziekbibliotheek wordt door deze installer niet aangeraakt.
