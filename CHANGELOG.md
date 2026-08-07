# Changelog

Alle noemenswaardige wijzigingen worden in dit bestand bijgehouden.

## [1.16.8] - 2026-08-07

### Toegevoegd

- Centrale persistente Multi Source Download Engine via `top40-download-manager.service`, onafhankelijk van de webapp op poort 8040.
- Modulaire providers voor SoundCloud, Audiomack, Audius, Bandcamp, YouTube Music en YouTube.
- Persistente downloadjobs, providerconfiguratie, health-state, circuit breakers, retryhistorie, zoekcache en geheugen voor afgewezen kandidaten.
- Provider-onafhankelijke matchscore voor artiest, titel, speelduur, album, jaar en ISRC met strafpunten voor ongewenste alternatieve versies.
- FFprobe/FFmpeg-validatie van iedere succesvolle download, inclusief audiostream, speelduur, minimale grootte en stiltecontrole.
- Registratie van broncodec, bronbitrate en sample rate naast de uiteindelijke outputkwaliteit.
- Download Providers-dashboard op `:8041/download-providers` met providerstatus, success rate, workers, cooldowns en YouTube-afhankelijkheid.
- Bounded Qwen/Ollama provider-tuning via `top40-provider-ai.timer` op basis van gemeten resultaten.

### Gewijzigd

- Chart-import, freshness-herstel en retries downloaden niet meer synchroon; zij enqueuen uitsluitend een job voor de zelfstandige manager.
- Maximaal vier globale downloadjobs worden parallel verwerkt, met afzonderlijke providerlimieten.
- Maximaal drie primaire providers worden per zoekgroep parallel bevraagd; YouTube Music en YouTube blijven sequentiële fallbackproviders.
- YouTube en YouTube Music gebruiken standaard maximaal één gelijktijdige provideractie en minimaal twintig seconden pacing.
- Jobretries volgen 30 seconden, 2 minuten, 10 minuten, 30 minuten en 2 uur terwijl andere providers beschikbaar blijven.
- De primaire KPI `YouTube dependency` telt alleen directe YouTube-downloads; YouTube Music en de gecombineerde YouTube-family worden afzonderlijk weergegeven.
- De AI-platformversie en sidecarversie worden voortaan uit het centrale `VERSION`-bestand gelezen.

### Veiligheid

- Gedownloade of reeds bestaande audio wordt nooit door de downloadmanager overschreven; een bestaand doelpad resulteert in een non-destructief conflict.
- Qwen kan providerprioriteit alleen begrensd bijstellen en een cooldown alleen bij concrete recente fouten verlengen.
- Qwen kan YouTube Music of YouTube nooit vóór primaire niet-YouTube-providers plaatsen.
- Accounts, persoonlijke cookies, captcha-omzeiling, rate-limit-bypass en proxyrotatie blijven expliciet verboden.
- De transactionele updater migreert van de oude downloader naar de nieuwe manager met geverifieerde backup, healthchecks en rollback naar de juiste downloadservice.

## [1.16.7] - 2026-08-07

### Opgelost

- Timer-gestuurde oneshot-services met een eerdere mislukte run worden niet meer als permanent kritiek gezien wanneer hun gekoppelde retry-timer gezond actief is.
- De auto-updater geeft root-aangemaakte `.git`-objecten na iedere update of rollback terug aan de repository-eigenaar, zodat handmatige Git-opdrachten als beheeraccount blijven werken.
- Root Git registreert alleen `/opt/top40-archiver` als veilige repository wanneer dat nodig is.
- De actuele chart-freshnesscontrole probeert voor de nieuwste verwachte editie eerst de live Top40.nl-pagina en daarna de gerichte week-URL, zonder ooit een weekmismatch op te slaan.

### Gewijzigd

- De freshness-cooldown is verlaagd van 20 naar 10 minuten.
- `top40-archiver-freshness.timer` controleert iedere 10 minuten na de vorige run in plaats van iedere 30 minuten.
- Gezonde operations-cycli slaan een overbodige Qwen-call over.
- Operations- en service-diagnose hebben een modeltimeout van 45 seconden en een begrensde output.
- Autonome code-repair gebruikt maximaal 16 kB foutbewijs, 32 kB broncontext en 60 seconden modeltijd.
- Tijdelijke Qwen-timeouts bij aanvullende diagnose of code-analyse blokkeren een verder geldige autonome policycyclus niet en wijzigen geen productiecode.
- De transactionele updater voert de nieuwe watchdog-regressietests tijdens de release-installatie uit.

### Veiligheid

- De dirty-worktreecontrole blijft onbekende lokale wijzigingen blokkeren; alleen aantoonbare actieve AI-canaries volgen het bestaande gecontroleerde handoff-pad.
- Gedownloade audio blijft uitgesloten van autonome verwijderacties.
- Vrije shelltoegang voor het model blijft uitgeschakeld.
- Autonome codepromotie vereist nog steeds sandboxvalidatie, een geverifieerde versiebackup en canary/rollbackcontrole.
- De geïnstalleerde commit-SHA wordt pas na de finale 8040/8041/8042-healthchecks gepromoveerd.

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
