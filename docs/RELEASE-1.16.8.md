# Top40Archiver 1.16.8 — Multi Source Download Engine

## Doel

Top40Archiver 1.16.8 vervangt de operationele afhankelijkheid van één YouTube-downloader door een centrale, persistente Multi Source Download Engine. YouTube Music en YouTube blijven beschikbaar als fallback, maar de coordinator probeert eerst alternatieve publieke audiobronnen en doseert iedere provider afzonderlijk.

Doel-KPI: directe YouTube-afhankelijkheid onder 10% zodra de alternatieve providers voldoende dekking leveren. YouTube Music wordt daarnaast apart en als onderdeel van een strengere YouTube-family KPI gemeten.

## Architectuur

Nieuwe permanente service:

- `top40-download-manager.service`

De webapp op poort 8040 voert geen externe downloadzoekopdracht meer uit. Chart-import, retries en freshness-herstel schrijven alleen een persistente `DownloadJob` naar SQLite. De manager claimt deze jobs onafhankelijk en verwerkt maximaal vier tracks tegelijk.

Jobstatussen:

- `queued`
- `searching`
- `downloading`
- `validating`
- `processing`
- `completed`
- `failed`
- `waiting_retry`
- `cancelled` voor een expliciete operatorannulering

## Providers

De providerinterface is modulair onder `app/providers/` en bevat in 1.16.8:

1. SoundCloud
2. Audiomack
3. Audius
4. Bandcamp
5. YouTube Music — fallback
6. YouTube — laatste fallback

De coordinator gebruikt per provider een eigen enabled-vlag, prioriteit, concurrencylimiet, requests-per-minute, minimale pauze, foutbackoff, health-status en cooldown.

Standaard is YouTube maximaal één gelijktijdige provideractie toegestaan en geldt minimaal 20 seconden pacing. De primaire providers hebben ieder hun eigen begrensde capaciteit. Maximaal drie providers uit een primaire zoekgroep worden parallel bevraagd; fallbackproviders worden sequentieel behandeld.

## Matchscore en versiecontrole

Kandidaten worden provider-onafhankelijk beoordeeld:

- artiest: 30 punten
- titel: 35 punten
- speelduur: 20 punten
- album: 5 punten
- jaar: 5 punten
- ISRC: 5 punten

Standaard strafpunten gelden voor onder meer karaoke, cover, tribute, nightcore, sped-up, slowed, live, instrumental, remix en radio edit. Een term krijgt geen straf wanneer die expliciet in de gewenste Top40-metadata staat.

Acceptatie:

- `>=92`: uitstekende match;
- `85–91`: accepteren als de speelduur maximaal zeven seconden afwijkt;
- `75–84`: niet downloaden, eerst andere provider proberen;
- `<75`: afwijzen.

Een speelduurverschil boven vijftien seconden is altijd een harde afwijzing.

## Persistente providerdata

Nieuwe SQLite-tabellen bewaren:

- downloadjobs en retryhistorie;
- providerconfiguratie en runtime-health;
- providerpogingen met zoektijd, downloadtijd, matchscore en foutcategorie;
- succesvolle zoekcache;
- afgewezen kandidaten met reden;
- broncodec, bronbitrate en sample rate naast outputcodec/bitrate.

Daardoor worden eerder afgewezen karaoke-, verkeerde duur- of andere ongeschikte URLs niet steeds opnieuw geprobeerd.

## Circuit breakers en retries

Fouten zoals 429, 403, captcha-indicatie en time-outs worden als providerproblemen gecategoriseerd. Vijf fouten binnen het lopende tienminutenvenster zetten een provider minimaal dertig minuten in degraded/cooldown; bij verdere opeenstapeling kan de provider offline gaan. Andere providers blijven ondertussen beschikbaar.

Jobbackoff volgt:

1. 30 seconden
2. 2 minuten
3. 10 minuten
4. 30 minuten
5. 2 uur

Een fout bij één provider blokkeert dus niet dat dezelfde track via een andere provider wordt gezocht.

## Audiovalidatie

Een download wordt pas voltooid nadat:

- het bronbestand bestaat en een minimale grootte heeft;
- het geen HTML-foutpagina is;
- FFprobe een audiostream vindt;
- de speelduur maximaal vijftien seconden afwijkt wanneer referentieduur beschikbaar is;
- een silence-detectie geen vrijwel volledig stil bestand vindt;
- FFmpeg een geldige MP3-uitvoer heeft gemaakt;
- het uiteindelijke bestand atomair naar de muziekmap is geschreven.

Bronkwaliteit wordt apart geregistreerd. Een lagere bronbitrate wordt dus niet administratief als echte 320-kbps-bron gepresenteerd, ook wanneer de outputcontainer als MP3 320 kbps wordt geschreven.

## API en toezicht op poort 8041

Nieuwe API:

- `GET /api/download/status`
- `GET /api/download/jobs`
- `GET /api/download/providers`
- `POST /api/download/retry/{track_id}`
- `POST /api/download/cancel/{track_id}`
- `POST /api/download/provider/{provider}/enable`
- `POST /api/download/provider/{provider}/disable`
- `POST /api/download/provider/{provider}/config`

Vaste toezichtpagina:

- `http://<host>:8041/download-providers`

Deze toont per provider status, healthscore, success rate, actieve/maximale workers, effectieve prioriteit, cooldown en recente foutcategorie. KPI's tonen downloads in 24 uur, zonder YouTube-family, via YouTube Music, via YouTube, directe YouTube dependency en daarnaast de YouTube-family dependency.

Dezelfde providerdata wordt opgenomen in de Operations Center-downloadsnapshot, zodat Qwen deze gegevens ook krijgt bij toekomstige veilige UI-optimalisaties.

## Qwen/Ollama

`top40-provider-ai.timer` laat de lokale Qwen periodiek alleen gemeten providerdata evalueren wanneer daar voldoende bewijs of een providerafwijking voor is.

Qwen mag binnen harde grenzen:

- een provider later of eerder binnen de primaire groep laten proberen via een kleine prioriteitscorrectie;
- YouTube/YouTube Music alleen gelijk of later laten proberen, nooit vóór primaire providers;
- bij concrete recente providerfouten een bestaande cooldown verlengen tot maximaal 120 minuten.

De modelcall is maximaal 30 seconden. Bij timeout of onbeschikbare Ollama verandert geen providerbeleid en blijft de vaste coordinator functioneren.

Qwen mag niet:

- accounts aanmaken;
- persoonlijke cookies gebruiken;
- captcha's omzeilen;
- rate limits ontwijken;
- proxies roteren om blokkades te omzeilen;
- shellcommando's verzinnen of uitvoeren;
- gedownloade audio verwijderen.

## Update en rollback

De 1.16.8-updater migreert transactioneel van `top40-archiver-download.service` naar `top40-download-manager.service`. De oude daemon wordt vóór de live codewissel gestopt en pas na succesvolle 8040/8041/8042- en managercontroles definitief uitgeschakeld.

Bij rollback wordt de oude downloadservice automatisch opnieuw gestart wanneer de nieuwe managerunit door het herstelpakket is verwijderd. De volledige versiebackup, databasebackups, Git-state en bestaande audio blijven onderdeel van het bestaande rollbackcontract.
