# Clusterherinrichting — werkdossier

Startdatum: 2026-11-20
Status: **inventarisatie gepland; geen systemen aangepast**
Repository: Techraym/Top40Archiver

## Doel
Bestaande vijf systemen inventariseren en veiligstellen; alleen onnodige software verwijderen; gezonde installaties behouden. Wijzigingen worden via branches, pull requests, controle en terugvalplan beheerd.

## Systeemindeling (voorgesteld, niet geverifieerd)
| Host | Beoogde functie | Te verifiëren |
| --- | --- | --- |
| Raspberry Pi | CHARLY 24/7 coördinator, monitoring, planning en aan/uit-beheer | SSH-toegang, betrouwbare opslag, netwerk, WOL-bereik |
| NUC13 | Top40 downloader, uploader, muziekopslag | disk mounts, taken, openstaande uploads, WOL vanuit S5 |
| NUC12 | KVM-host voor Windows 11 OrderDesk en toekomstige ontwikkel-VM's | CPU/RAM/SSD, VT-x, bestaande OrderDesk-data |
| Shuttle 1 | AI of TTS, afhankelijk van hardwaremeting | CPU/RAM/GPU, snelheid |
| Shuttle 2 | AI/TTS of reserve, afhankelijk van hardwaremeting | CPU/RAM/GPU, snelheid |

**AI-locatie is nog niet gekozen.** Benchmark op echte controlewerklast; bescherm OrderDesk-VM tegen resourceconcurrentie.

## Onmisbare functies
- Top40 downloader en uploader, inclusief queuestatus, configuratie en overdrachten
- Muziekarchief, metadata, covers en mounts; geen ongewenst formatteren
- Beste passende AI-controle en TTS-nieuwslezer
- CHARLY monitoring, taakcoördinatie, begrensde herstelacties en energiebeheer
- OrderDesk (bestaande Windows-app) in Windows 11-VM; functionaliteit ongewijzigd
- Ontwikkel-/virtualisatiemogelijkheden op NUC12

## Werkafspraken
1. Eerst **read-only** inventariseren via bestaande CHARLY-SSH-verbindingen. Geen reboot, stop, delete of install tijdens inventarisatie.
2. Back-up vóór systeemwijziging op twee onafhankelijke locaties, met checksum en aantoonbare hersteltest. Vastleggen: locatie, eigenaar, datum, resultaat. Geen back-upbytes in Git.
3. Per host beslissen: behouden / opschonen / herinstalleren (alleen bij noodzaak).
4. Eerst stop/disable met terugvalplan, daarna pas eventueel verwijderen.
5. Voor iedere technische wijziging: GitHub issue of PR met doel, getroffen hosts, dependencies, back-upverwijzing, verificatie, rollback en resultaat.
6. Behandel SSH-sleutels, wachtwoorden, tokens, persoonsgegevens, database-inhoud, complete configs met geheimen en ruwe logs als **geheim**. Nooit committen; alleen geredigeerde inventarisgegevens.
7. Geen uitrol naar hosts zonder expliciete uitvoeringsstap en gevalideerde SSH-targets.

## CHARLY automatisch energiebeheer (ontwerpvereiste)
- Raspberry Pi blijft aan, maar is geen verplichte netwerkrouter.
- Per host controleren: Wake-on-LAN ondersteund, geactiveerd in NIC en BIOS/UEFI, fysiek getest vanaf uitgeschakelde toestand.
- Work queue / plan wordt buiten een uitgeschakelde host bewaard.
- Host alleen uitschakelen bij lege queue én geen actieve downloads, uploads, VM-sessies, externe opslagafhankelijkheden of schrijfacties.
- Graceful shutdown, bevestiging en logging; timeouts, beperkte retries en foutmelding.
- Als muziekbestanden op NUC13 nodig zijn voor TTS/andere hosts, blijft NUC13 actief tot alle clients klaar zijn.
- Hard power-cut niet als standaard herstelmechanisme.

## Fasen
| Fase | Oplevering | Status |
| --- | --- | --- |
| 1 Inventarisatie | Rapport per apparaat, netwerk en afhankelijkheden | Open |
| 2 Back-up | Back-upregister, checksums, hersteltest | Open |
| 3 Beslissen | Behoud-/opschoon-/herinstallatielijst | Open |
| 4 Opschonen | Beperkte wijzigingen, per host gecontroleerd | Open |
| 5 Herinrichten | VM's, AI, TTS, Top40, CHARLY | Open |
| 6 Acceptatie | Functietest en energiebeheer inclusief rollback | Open |

Zie [inventarisatie-sjabloon](INVENTARISATIE.md).