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
