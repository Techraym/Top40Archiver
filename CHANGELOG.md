# Changelog

Alle noemenswaardige wijzigingen worden in dit bestand bijgehouden.

## [1.9.0] - 2026-08-04

### Toegevoegd

- Mislukte downloads gebruiken maximaal acht unieke YouTube-zoekvarianten met maximaal acht kandidaten per zoekopdracht.
- Spotify-metadata wordt, wanneer beschikbaar, als alternatieve artiest- en titelcombinatie meegenomen in de selectie.
- Een verdwenen eerder opgeslagen YouTube-URL valt automatisch terug op een nieuwe zoekronde.
- Het dashboard bevat per mislukte track de actie `Niet meer beschikbaar`.
- Niet-beschikbare tracks blijven in de hitlijsthistorie en database bewaard, maar worden uitgesloten van automatische downloads.
- Niet-beschikbare tracks kunnen later met `Toch opnieuw proberen` weer worden geactiveerd.

### Gewijzigd

- Handmatig en gezamenlijk opnieuw proberen zet de pogingsteller terug op nul en verwijdert een mogelijk verouderde YouTube-URL.
- Foutmeldingen tonen de gebruikte zoekvarianten wanneer geen betrouwbare kandidaat wordt gevonden.
- De updater voert pakket- en Python-voorbereiding uit terwijl de bestaande webinterface blijft draaien.
- De applicatie wordt pas aan het einde kort omgeschakeld en automatisch teruggedraaid wanneer de healthcheck mislukt.
- De webservice gebruikt `Restart=always`, een herstartvertraging van twee seconden en begrensde start- en stoptijden.

### Veiligheid

- De selectie blijft een minimale overeenkomstscore en eventuele speelduurcontrole gebruiken.
- `Niet meer beschikbaar` verwijdert geen track- of hitlijstrecords uit SQLite.
- De globale workerlock en de begrenzing tot maximaal vier workers blijven actief.

## [1.8.6] - 2026-08-04

### Gewijzigd

- De systeemcontrole toont het schijfgebruik voortaan met drie decimalen, zodat kleine hoeveelheden op een schijf van 1,8 TB niet meer als `0%` worden weergegeven.
- De backend registreert naast vrije, gebruikte en totale schijfruimte ook het werkelijke aantal MP3-bestanden en de totale MP3-grootte.
- De recursieve muziekscan wordt 30 seconden gecachet, zodat de live dashboardupdate van één seconde de schijf niet voortdurend volledig doorloopt.
- Symbolische links worden bij de muziekscan niet gevolgd.

## [1.8.5] - 2026-08-04

### Gewijzigd

- De downloadwachtrij gebruikt standaard twee parallelle workers.
- Eén globale proceslock blijft dubbele service-runs voorkomen.
- Iedere worker gebruikt eigen korte SQLite-verbindingen; WAL en een timeout van 60 seconden blijven actief.
- Het aantal workers is instelbaar via `download_workers` en wordt voor veiligheid begrensd op maximaal vier.
- `history_download_limit` blijft het totale aantal nummers per batch, niet het aantal per worker.

### Veiligheid

- Tracks worden nog steeds slechts eenmaal uit de wachtrij geselecteerd binnen de globale workerlock.
- Tijdelijke downloadmappen blijven per track uniek.
- Eén mislukte worker stopt de overige downloads in dezelfde batch niet.

## [1.8.4] - 2026-08-04

### Gewijzigd

- Genre-indeling gebruikt voortaan dezelfde gesloten normalisatieregels als GenreSplitter.
- De mapstructuur gebruikt dezelfde artiest-buckets: `0-9`, `A` t/m `Z` en Windows-veilig `!-_`.
- Speciale GenreSplitter-regels voor Piratenmuziek en kerstmuziek zijn overgenomen.
- Apple iTunes-genregegevens worden niet meer met een Nederlandse storefront geforceerd, zodat de ruwe genrenamen gelijk lopen met GenreSplitter.
- Onbekende of niet-herkende genres komen in `Other` terecht in plaats van willekeurige nieuwe genremappen te maken.
- De bestaande opdracht `organize` kan al gedownloade bestanden opnieuw indelen zonder ze opnieuw te downloaden.

### Tests

- Regressietests toegevoegd voor genre-normalisatie, speciale overrides en artiest-buckets.

## [1.8.3] - 2026-08-04

### Opgelost

- De actuele HTML-structuur van Top40.nl met `.top40-list__item` wordt opnieuw correct verwerkt.
- Titel en artiest worden uit de tekstlinks naar de nummerdetailpagina gelezen wanneer oude titel- en artiestclasses ontbreken.
- Historische jaartallen vanaf 1965 worden correct uit paginatitels en URL's gelezen; de parser accepteert nu zowel 19xx als 20xx.
- Regressietests toegevoegd voor Tipparade 1967-W28 met 20 noteringen en een actuele Tipparade met 30 noteringen.

## [1.8.2] - 2026-08-04

### Opgelost

- De TLS-installatie is niet meer afhankelijk van het downloadformaat van `crt.sh`.
- Sectigo DV R36 en Root R46 worden via vaste Sectigo-adressen gedownload.
- Zowel PEM als DER wordt automatisch herkend.
- Beide certificaten worden gecontroleerd tegen een vastgelegde SHA-256-vingerafdruk voordat ze worden gebruikt.
- Top40Archiver gebruikt voortaan `/etc/top40-archiver/top40-ca-bundle.pem` rechtstreeks; de `certifi`-pakketbestanden worden niet meer aangepast.

### Veiligheid

- TLS-verificatie en hostnaamcontrole blijven actief.
- Een download via de HTTP-reserve-URL wordt alleen geaccepteerd wanneer de volledige SHA-256-vingerafdruk exact overeenkomt.
- De certificaatketen en de uiteindelijke HTTPS-verbinding met Top40.nl worden na installatie gecontroleerd.

## [1.8.1] - 2026-08-04

### Opgelost

- Top40.nl TLS-fouten door een onvolledige Sectigo-certificaatketen.
- Gecontroleerde installatie van `Sectigo Public Server Authentication CA DV R36` en de cross-sign `Sectigo Public Server Authentication Root R46 x USERTrust RSA`.
- Certificaten worden op subject, issuer en cryptografische keten gecontroleerd voordat ze in de Top40Archiver CA-bundle worden opgenomen.
- De uiteindelijke HTTPS-verbinding met Top40.nl wordt na installatie getest.
- De CA-bundle wordt na iedere installatie en update opnieuw toegepast, zodat een pip-upgrade de reparatie niet verwijdert.
- Deno-installatie gebruikt nu de correcte `DENO_INSTALL`-omgeving voor het installatiescript.

### Veiligheid

- TLS-verificatie blijft volledig actief; `verify=False` wordt niet gebruikt.
- De Debian CA-bundle blijft de basis van de applicatiebundle.
- Alleen de officiële Sectigo-certificaten met vaste certificate-transparency-ID's worden toegevoegd.

## [1.8.0] - 2026-08-04

### Toegevoegd

- Automatische GitHub-updatecontrole bij iedere systeemstart.
- Daarna iedere 24 uur opnieuw controleren via een systemd-timer.
- Vergelijking van de lokaal geïnstalleerde commit-SHA met de actuele SHA van `main`.
- Download van de broncode via een vastgepinde commit-SHA in plaats van een veranderlijke branch-ZIP.
- SHA-256-berekening van ieder gedownload updatearchief.
- Permanente updategegevens in `/var/lib/top40-archiver/update-state`.
- Handmatige update controleert na installatie of de toegepaste SHA overeenkomt met GitHub.

### Veiligheid

- De lokaal geregistreerde commit-SHA wordt alleen aangepast nadat de volledige update is geslaagd.
- Bij een mislukte download, installatie of SHA-controle blijft de vorige installatie als geregistreerde versie behouden.
- De SQLite-database, instellingen, historische voortgang en externe muziekopslag worden niet vervangen.

## [1.7.0] - 2026-08-03

### Toegevoegd

- Actuele en historische Nederlandse Top 40.
- Actuele en historische Tipparade.
- Permanente deduplicatie met SQLite.
- Spotify uitsluitend als metadata-controle.
- YouTube-zoekselectie en MP3-download via yt-dlp en FFmpeg.
- Opslag als `Genre/beginletter/Artiest - Titel.mp3`.
- Hervatbare historische import vanaf 1965 en 1967.
- Compact live dashboard met FastAPI.
- Systemd-services en timers voor actuele en historische controles.
- Externe USB-C-opslag als Windows-netwerkschijf via Samba.
- Directe update vanaf GitHub met `update-from-github.sh`.

### Belangrijk

- De database blijft leidend wanneer MP3-bestanden van de externe schijf worden verwijderd.
- Een eenmaal succesvol verwerkt nummer wordt niet opnieuw gedownload.
