# Architectuur

## Overzicht

Top40Archiver 1.16.22 bestaat uit afzonderlijke functionele lagen. De hoofdwebapplicatie verwerkt geen langdurige externe downloads meer rechtstreeks.

```text
Top 40 / Tipparade
        ↓
chart import + freshness
        ↓
SQLite
        ↓
persistente download_jobs
        ↓
top40-download-manager.service
        ↓
providerselectie en matching
        ↓
download
        ↓
FFprobe / FFmpeg-validatie
        ↓
definitieve audio-opslag
        ↓
cover-art worker
```

Daarnaast draait een gescheiden lokale AI-beheerlaag:

```text
8040  hoofdapplicatie
8041  AI Control Room / Operator Chat
8042  lokale Log & AI Control service
11434 Ollama
```

## Database

De hoofddatabase staat standaard op:

```text
/var/lib/top40-archiver/top40.sqlite3
```

De database is leidend voor de archiefstatus. Een track met status `downloaded` blijft verwerkt wanneer het audiobestand later wordt verplaatst of verwijderd.

AI-state en learning worden afzonderlijk opgeslagen, onder andere in:

```text
/var/lib/top40-archiver/ai_memory.sqlite
```

SQLite gebruikt waar nodig WAL voor veilige gelijktijdige toegang.

## Downloadarchitectuur

Downloads worden persistent als jobs verwerkt door:

```text
top40-download-manager.service
```

Chart-imports, retries en freshness-processen enqueue'en werk en hoeven niet op externe providers te wachten.

De manager bewaakt onder andere:

- jobstatus en retrystatus;
- providerpogingen en kandidaten;
- providerhealth en cooldowns;
- circuit breakers;
- globale en provider-specifieke concurrency.

## Matching en validatie

Kandidaten worden beoordeeld op artiest, titel en beschikbare aanvullende metadata. Ongewenste alternatieven zoals previews, karaoke, tribute, covers en verkeerde versies worden afgewezen of bestraft.

Na downloaden vindt technische validatie plaats met FFprobe/FFmpeg voordat een bestand naar de definitieve muziekopslag wordt gepromoveerd.

## Audioveiligheid

Belangrijke invariant:

```text
Bestaande gedownloade audio niet autonoom verwijderen of overschrijven.
```

De downloadpipeline gebruikt een non-destructieve eindstap en valideert audio vóór definitieve opslag.

## Opslag

Definitieve muziekopslag:

```text
/mnt/top40-music/Top40/<Genre>/<bucket>/<Artiest - Titel.mp3>
```

Tijdelijke download- en conversiebestanden:

```text
/var/lib/top40-archiver/download-temp
```

## Covers

`top40-archiver-cover-art.service` verwerkt ontbrekende albumhoezen continu. Actuele hitlijsten krijgen voorrang voordat historische coverachterstand verder wordt verwerkt.

## Web- en AI-laag

### 8040

`top40-archiver-web.service`

Normale menselijke hoofdinterface en API. Deze laag moet beschikbaar blijven wanneer de AI-laag problemen ondervindt.

### 8041

`top40-archiver-ai.service`

AI Control Room, Operator Chat, status, diagnose en begrensde AI-beheerfunctionaliteit.

### 8042

`top40-log-reader.service`

Lokale log- en controlservice. Deze service is bedoeld voor lokaal/trusted gebruik en hoort niet publiek op internet te worden aangeboden.

### Ollama

De lokale AI-runtime gebruikt Ollama/Qwen. Het model heeft geen onbeperkte vrije shell en mag harde veiligheidsgrenzen niet autonoom versoepelen.

## AI-beveiligingsgrenzen

Tot de beschermde uitgangspunten behoren:

- 8040 beschikbaar houden;
- geen autonome audioverwijdering;
- geen overschrijven van bestaande audio;
- geen CAPTCHA-bypass;
- geen rate-limit-bypass;
- geen proxyrotatie als ontwijkingsmechanisme;
- geen gebruik van persoonlijke accounts/cookies als autonome workaround;
- menselijke HOLD/guidance respecteren;
- geverifieerde backup, validatie, canary en rollback bij risicovolle codepromoties.

## Belangrijkste services

```text
top40-archiver-web.service
top40-archiver-ai.service
top40-download-manager.service
top40-log-reader.service
top40-archiver-cover-art.service
ollama.service
```

Daarnaast zijn er timers/workers voor onder meer chart freshness, actuele controles, historie, provider-AI en automatische updates.

## Updatearchitectuur

Officiële updates komen vanaf GitHub `main`.

Een update moet:

1. de doelcommit bepalen;
2. de updatebron vastpinnen;
3. rollbackinformatie behouden;
4. de applicatie gecontroleerd bijwerken;
5. healthchecks uitvoeren;
6. pas daarna de nieuwe versie als succesvol registreren.

Release 1.16.22 bevat de compatibiliteitsbootstrap:

```text
scripts/install-1.16.22.sh
```
