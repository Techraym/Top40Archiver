# Inventarisatie en herstelregister

**Status:** nog geen live hostgegevens ontvangen. Vul uitsluitend geverifieerde, geredigeerde resultaten in.

| Host | SSH gecontroleerd | CPU/RAM/GPU | OS | Opslag/mounts | Services/timers/containers | WOL/S5 getest | Back-up en hersteltest | Besluit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Raspberry Pi | Open | Open | Open | Open | Open | n.v.t. | Open | Open |
| NUC12 | Open | Open | Open | Open | Open | Open | Open | Open |
| NUC13 | Open | Open | Open | Open | Open | Open | Open | Open |
| Shuttle 1 | Open | Open | Open | Open | Open | Open | Open | Open |
| Shuttle 2 | Open | Open | Open | Open | Open | Open | Open | Open |

## Minimaal per host vastleggen
- Hostnaam, OS/kernel, bootmethode, CPU, RAM, GPU en vrije schijfruimte
- Schijf-ID, partities, bestandenstelsel, mounts, externe opslag en fysieke back-uplocaties
- Enabled/running systemd services, timers, containers, processen, bind/listen ports
- Applicatielocaties, databases, queues, versies en start-/herstelprocedure
- SSH-connectiviteit vanaf CHARLY, NIC/WOL en BIOS-instellingen waar controleerbaar
- Dependencies: wie gebruikt NUC13-muziekshare; OrderDesk/VM; AI/TTS-diensten
- Alleen redacteerde resultaten opnemen, geen geheime configuratiebestanden

## Back-upregister (voorbeeldvelden)
| Systeem/app | Type data | Bron | Doel A | Doel B | Datum | Controle SHA256 | Herstelproef | Eigenaar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Nog in te vullen | | | | | | | | |

**Acceptatie voor opschonen:** twee onafhankelijke kopieën, integriteitscontrole en herstelproef geslaagd, en getroffen afhankelijkheden in kaart.

## Wijzigingenlog
| Datum | Host | Issue/PR | Wijziging | Voorcontrole | Na-controle | Rollback | Uitkomst |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-20 | alle | dit dossier | Alleen documentatie voorbereid | n.v.t. | n.v.t. | n.v.t. | Geen hostwijziging |


## Eerste live inventarisatie — 2026-11-20 22:19 CET
Bron: uitlezende Bash-uitvoer via CHARLYPi, aangeleverd in de chat. Dit is een momentopname, geen volledige audit. Ruwe uitvoer bevat interne adressen en wordt niet in Git opgeslagen.

| Host | SSH | CPU | RAM zichtbaar | Lokale opslag | Belangrijkste geobserveerde services | Beoordeling |
| --- | --- | --- | --- | --- | --- | --- |
| NUC12WSH | gelukt | i3-1220P, 10 cores / 12 threads | 15 GiB | NVMe 465,8G plus SSD 238,5G (/srv/charly-ai) | Ollama, Ornith, resource control, vele video-/VNC-/FFmpeg-diensten | Behouden, video-stack eerst dependency-check, KVM-capaciteit later toetsen |
| Top40 (NUC13) | gelukt | i3-1315U, 6 cores / 8 threads | 15 GiB | NVMe 238,5G | downloader, web, AI, covers, Redis, Samba, studio-upload timer | Behouden; **externe muziekschijf niet zichtbaar** |
| Shuttle1 | gelukt | Celeron 3855U, 2 cores / 2 threads | 3,7 GiB | 111,8G | CHARLY backend/router/agent/task worker/broker, Prometheus, GitHub runner | Cruciale controller-dependencies vóór migratie vastleggen |
| Shuttle2 | gelukt | Celeron 3855U, 2 cores / 2 threads | 7,6 GiB | 111,8G | PostgreSQL 17, monitor, video/VNC | Databasefunctie en afhankelijkheden uitzoeken |
| CHARLYPi | lokale inventaris uitgevoerd | rapport local.txt niet meegestuurd | onbekend | onbekend | onbekend | Volledig rapport nog opvragen |

### Risico's en vervolgcontroles
1. **NUC13:** `lsblk` en `df` tonen alleen interne NVMe; controleer `/mnt/top40-music`, `findmnt`, `lsblk -f`, `/etc/fstab` (geheimen redigeren), aanwezigheid externe schijf, opslagbehoefte. Niet formatteren of blind opnieuw mounten.
2. **NUC12:** meerdere `charly-video-*`, `charly-fourup-*`, VNC, Xvfb, FFmpeg en MediaMTX actief. Kandidaten om te verwijderen, maar eerst `systemctl cat`, reverse-dependencies en actuele gebruiksfunctie bepalen.
3. **Shuttle1:** CHARLY is nog niet volledig gecentraliseerd op Raspberry Pi; services, runner en token-/databaseafhankelijkheden migratieplan geven, secrets uitsluitend in beveiligde back-up.
4. **Shuttle2:** PostgreSQL 17 niet stoppen vóór database-inventarisatie, consistente export en hersteltest.
5. **NUC13:** `top40-studio-upload.timer` aanwezig; uploader behouden. Controleren of taken en status persistent zijn vóór geautomatiseerde shutdown.
6. **AI:** NUC12 heeft `qwen3.5:4b` en `huihui_ai/qwen3.5-abliterated:4b`; NUC13 aanvullend `qwen3:4b`. Niet verwijderen zonder dependency-/kwaliteitscontrole en benchmark. Dualcore-Shuttles niet aannemen als geschikte primaire LLM-host.
7. **WOL:** geen NIC/BIOS S5-onderzoek uitgevoerd, dus autonoom powerbeheer nog niet bewezen.
8. **Back-ups:** bestaande `charly-ai-node-backup.timer`, `charly-nuc13-backup.timer`, `charly-backup.timer`, `charly-postgres-backup.timer` zijn zichtbaar, maar succesvolle uitvoering, tweede kopie en herstelbaarheid zijn niet aangetoond.

**Geen wijzigingen uitgevoerd op hosts, en nog geen back-ups geverifieerd.**


## Aanvullende controle — CHARLYPi en NUC13 2TB (2026-11-20)

### CHARLYPi (geobserveerd)
- Debian 13 (Trixie), 4x ARM Cortex-A53, 905 MiB RAM, 411 MiB available ten tijde van meting.
- SD: 15G device, root ca. 14.5G, 9.0G vrije ruimte.
- Doelrol: lichtgewicht 24/7 CHARLY scheduler, SSH/Wake-on-LAN coördinator, statusbewaking. Zware AI, TTS, databases, grote metrics-opslag niet op Pi.
- Werkelijke lopende diensten op Pi blijven nog te inventariseren; het eerdere `local.txt` is nog niet inhoudelijk overgenomen.

### NUC13 muziekarchief (geobserveerd)
- Alleen interne NVMe zichtbaar in `lsblk -f`.
- `findmnt /mnt/top40-music`: **systemd autofs placeholder**; dit bewijst niet dat de daadwerkelijke USB-schijf gemount is.
- `mountpoint -q /mnt/top40-music`: negatief; `lsusb` toont geen externe opslag.
- Gebruikersbesluit: **2 TB externe muziekschijf later onderzoeken**. Niets aan mountconfiguratie, partitietabel of data wijzigen.
- Risicobeheersing: downloader/uploader niet naar interne root laten terugvallen als muziek-mount ontbreekt; queue en outputpad eerst controleren.

### Volgende stap
Back-upbronnen, bestaande backup-timers, app-afhankelijkheden en SSH/WOL zonder systeemwijzigingen uitzoeken. Back-ups zelf alleen op onafhankelijke opslaglocaties, nooit in Git.


## Back-uptimerinventarisatie — 2026-11-20 ca. 22:23 CET

Uitvoer van read-only `systemctl list-timers`, `systemctl list-unit-files` en `df -hT` op alle hosts. Alle vijf hebben een **enabled** hostspecifieke back-uptimer en recent ingevulde LAST-timestamp. **Succes, doelpad, volledigheid, tweede kopie en herstelproef zijn niet geverifieerd.**

| Host | Timer / service | Eerstvolgende geplande start (CET, 21 nov) | Laatste geregistreerde trigger (20 nov) | Status |
| --- | --- | --- | --- | --- |
| NUC12 | charly-ai-node-backup | 03:39:51 | 22:17:02 | Timer enabled; back-upresultaat onbekend |
| NUC13 | charly-nuc13-backup | 03:49:26 | 22:16:36 | Timer enabled; back-upresultaat onbekend |
| Shuttle1 | charly-backup | 03:17:29 | 22:17:10 | Timer enabled; back-upresultaat onbekend |
| Shuttle2 | charly-postgres-backup | 03:59:07 | 22:16:54 | Timer enabled; databaseconsistentie/herstel onbekend |
| CHARLYPi | charlypi-backup | 03:26:05 | 22:13:49 | Timer enabled; back-upresultaat onbekend |

`dpkg-db-backup.timer` draait daarnaast op alle systemen, maar is géén volledige applicatie-/systeemback-up. Shuttle2 heeft tevens uitgeschakelde `pg_basebackup@.timer`-template.

### Schijfruimte (afgeronde gerapporteerde filesystems)
- NUC12: systeem-root 442G totaal / 15G gebruikt / 404G beschikbaar; /srv/charly-ai 234G / 21G / 214G.
- NUC13: root 226G / 57G / 158G. Externe 2TB niet aangesloten/gemount: onderzoek uitgesteld.
- Shuttle1: root 106G / 9.4G / 91G.
- Shuttle2: root 106G / 2.7G / 98G.
- CHARLYPi: root 15G / 4.7G / 9.0G.

**Volgende controles (read-only):** `systemctl show` van vijf services met `Result`, `ExecMainStatus`, `ActiveEnterTimestamp`; afgeronde, geredigeerde journalregels; op locatie back-up-output zoeken zonder toegangstokens of gevoelige data te publiceren. Geen back-ups runnen of wijzigen tot bestemming en vrije capaciteit vaststaan.


## Back-up execution status and temporary target — 2026-11-20

All five host-specific backup services returned `Result=success`, `ExecMainCode=1` (normal exit) and `ExecMainStatus=0` on last recorded execution:
- NUC12 `charly-ai-node-backup.service` — inactive 22:17:03 CET
- NUC13 `charly-nuc13-backup.service` — inactive 22:16:37 CET
- Shuttle1 `charly-backup.service` — inactive 22:17:10 CET
- Shuttle2 `charly-postgres-backup.service` — inactive 22:16:55 CET
- Pi `charlypi-backup.service` — inactive 22:13:56 CET

**Interpretation:** success of the service process ONLY, not proof that archive contents are valid or recoverable.

User approved considering extra disk mounted at NUC12 `/srv/charly-ai` as temporary centralized staging storage. Prior `df`: approx 234G filesystem, 21G used, 214G available. Proposed subdirectory `/srv/charly-ai/cluster-backups` is NOT yet created. Protect existing AI data and confirm source/device/contents/space prior to writing. Existing NUC12 local backups there are NOT an independent copy; obtain verified independent copy before destructive cleanup.

Pending read-only check: `findmnt -T /srv/charly-ai`, `lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS`, `du -h --max-depth=1 /srv/charly-ai`, available space, and backup output artifacts with credentials redacted.


## NUC12 externe USB-SSD inhoud — 2026-11-20

Read-only inspectie vanaf CHARLYPi via `ssh nuc12`. Device: Samsung MZVL2256HCHQ-00B00, USB SSD, `/dev/sda1`, ext4, `/srv/charly-ai`. `df`: 234G filesystem, 21G gebruikt, 214G vrij. **Geen files gewijzigd.**

| Onderdeel | Omvang (du, afgerond) |
| --- | --- |
| `models/colibri` | 7.0G |
| `models/ollama` | 6.3G |
| `models/ornith` | 5.4G |
| `runtime` | 1.4G |
| `cache` | 227M |
| overige | gering |

Grootste `ornith` bestand: `models/ornith/Ornith-1.5-9B-Q4_K_M.gguf` circa 5.38 GiB. `models/colibri` bevat meerdere safetensors van olmoe-1b-7b-instruct. Er staan ook llama.cpp- en Python-runtimebestanden.

**Besluit:** AI-data eerst behouden. De SSD kan dienen als tijdelijke cluster-back-upstaging in nieuwe geïsoleerde directory `/srv/charly-ai/cluster-backups`, nog niet aangemaakt. Niet claimen als tweede onafhankelijke kopie van NUC12-data of deze SSD. Voor bestanden verplaatst/verwijderd worden: ander fysiek opslagmedium en herstelcontrole; back-upomvang inclusief datastore, database en applicatiestatus nog bepalen. Inventariseren welke AI-diensten de SSD actief gebruiken.


## Besluit gebruiker — NUC12 externe SSD opschonen (2026-11-20)

Gebruiker heeft expliciet opdracht gegeven om AI-modellen onder `/srv/charly-ai/models` van de USB-SSD van NUC12 te verwijderen en daarna cluster-back-upwerk te hervatten. Betreft `ornith` (5.4G), `colibri` (7.0G), `ollama` (6.3G), circa 18.7G totaal. **Geen hostdelete vanuit GitHub uitgevoerd.**

Veilige uitvoering:
- Controleer dat mount daadwerkelijk de externe Samsung SSD is; root van NUC12 is andere fysieke NVMe.
- Archiveer/repliceer modellen naar andere fysieke media met volledige verificatie of noteer dat deze bewust niet herstelbaar zullen zijn. Bestaande runtime, cache, workspaces en backups ongemoeid laten.
- Ornith en Ollama kunnen nog in gebruik zijn. Eerst service-configuraties en afhankelijkheden beoordelen; pas stoppen/disable indien de gebruiker deze diensten op NUC12 niet meer nodig heeft. Belangrijk: dit kan huidige CHARLY AI-routing beïnvloeden.
- Bij gedeeld opslagpad beslist geen brede `rm -rf /srv/charly-ai` en geen formattering uitvoeren.
- Na veilige opschoning aparte back-updirectory voorbereiden; controleer effectieve capaciteit en backupbestemmingen, verificatie en tweede locatie voor destructieve clusteropschoning.
