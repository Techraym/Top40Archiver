# Changelog

Alle noemenswaardige wijzigingen worden in dit bestand bijgehouden.

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
- Externe opslag via Samba beschikbaar maken voor Windows.
- Directe update vanaf GitHub met `update-from-github.sh`.

### Belangrijk

- De database blijft leidend wanneer MP3-bestanden van de externe schijf worden verwijderd.
- Een eenmaal succesvol verwerkt nummer wordt niet opnieuw gedownload.
