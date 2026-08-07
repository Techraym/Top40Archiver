# Top40Archiver 1.16.4 — Continuous Autonomy + Chart Freshness

## Actuele Top 40 en Tipparade

- Vrijdag vanaf 12:00 CEST verwacht de freshness-guard de actuele ISO-week.
- Op vrijdag 7 augustus 2026 is dat week 32.
- `top40-archiver-freshness.timer` controleert na boot en iedere 30 minuten.
- Ontbrekende weken worden chronologisch ingehaald; een mislukte tussenweek wordt niet overgeslagen.
- Na installatie wordt een freshness-run direct gestart.

## Continuous online learning

- Leren begint bij actie 1.
- Iedere uitgevoerde beheeractie krijgt oorzaak, voorstatus, resultaat, nastatus en effectscore.
- Uitgestelde acties worden later op het werkelijke resultaat geverifieerd.
- Zeven dagen is alleen een rolling trendvenster en geen wachtdrempel.
- De volgende actie gebruikt direct de beschikbare geverifieerde ervaring.

## Autonomous code repair

- Alleen aangetoonde runtimefouten uit `app/*.py` komen in aanmerking.
- Eerste waarneming: analyse + sandboxpatch + syntaxcontrole + regressietests.
- Tweede onafhankelijke waarneming: een reeds gevalideerde patch kan direct naar canary.
- Voor productiepromotie is een geverifieerde versiebackup verplicht.
- Canary-healthchecks bewaken 8040, 8041 en 8042; terugkerende fout of health failure rolt automatisch terug.
- De AI mag zijn eigen learning-, backup-, watchdog-, database- of veiligheidsbeleid niet autonoom herschrijven.

## Evidence-driven improvements

- Herhaald beheerwerk wordt over zes uur gemeten.
- Vanaf vijf herhalingen mag een functionele optimalisatie in de sandbox worden onderzocht.
- Alleen vooraf bepaalde functionele modules zijn wijzigbaar.
- Een verbetering blijft alleen staan wanneer de recovery-rate gedurende de canary aantoonbaar minimaal 50% daalt; anders rollback.

## Audio safety

- Gedownloade nummers worden nooit door AI verwijderd.
- Geen vrije shell.
- `rm`, `unlink` en `shred` zijn geen toegestane AI-acties.
- Opslagherstel mag alleen oude onvoltooide tijdelijke `.part`, `.tmp` en `.ytdl`-bestanden opruimen.

## Backups en updates

- Iedere versie-update vereist vooraf een verifieerbare rollback-backup met `BACKUP_OK` en SHA-256-manifest.
- Backup bevat Git-revisie/bundle, applicatiecode, systemd-configuratie, hoofd- en AI-memorydatabase.
- Normale rollback laat actuele databasevoortgang en gedownloade audio ongemoeid.
- Een actieve gevalideerde AI-codecanary blokkeert officiële updates niet: de lokale diff wordt voor rollback bewaard en na succesvolle update neutraal als `superseded` afgesloten.
