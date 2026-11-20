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
