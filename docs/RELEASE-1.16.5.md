# Top40Archiver 1.16.5 — AI Control Room

## Doel

Poort 8041 is de centrale cockpit van de lokale AI. De pagina maakt zichtbaar wat de AI bewaakt, welke taken openstaan, welke acties zij uitvoert, wat er vóór en na een actie veranderde, welke codewijzigingen actief zijn en wat uit eerdere resultaten is geleerd.

## Lokale AI bezit de pagina

Qwen `qwen3:4b` schrijft en verbetert lokaal de HTML/CSS van de hoofdroute `/` op poort 8041.

De applicatie bewaart een vaste, gecontroleerde runtime voor data-injectie en browsertelemetrie. Door de lokale AI gegenereerde pagina's mogen geen JavaScript, externe URL's, iframes, forms of inline event-handlers bevatten. Daardoor kan een layoutwijziging nooit vrije systeemacties toevoegen.

Verplichte observability-secties blijven altijd aanwezig:

- systeemoverzicht;
- actieve taken;
- AI-acties met voor/na/resultaat;
- services en timers;
- downloads;
- covers;
- database;
- Top 40 en Tipparade;
- incidenten;
- codeherstel en gemeten codeverbeteringen;
- learning;
- UI-evolutie;
- foutlogs;
- volledige ruwe live snapshot.

## UI learning loop

Iedere UI-revisie is een normale AI-actie in `ai_memory.sqlite`:

1. aanleiding vaststellen;
2. Qwen krijgt actuele operations-, task-, learning- en telemetrycontext;
3. volledige HTML/CSS genereren;
4. structureel veiligheidscontract controleren;
5. eerdere pagina back-uppen;
6. nieuwe revisie als canary publiceren;
7. browser rapporteert page-health, ontbrekende secties, horizontale overflow, API-fouten en JavaScript/runtimefouten;
8. revisie verifiëren of automatisch terugrollen;
9. effect als success/failure in de bestaande online-learningdatabase verwerken.

De worker mag na stabiel gebruik periodiek opnieuw optimaliseren. Er is geen kalenderwachttijd voordat UI-resultaten geleerd worden.

## Centrale Control Room API

`GET /api/ai/control-room` levert één snapshot met health, Ollama, autonomie, taken, acties, cycli, services, downloads, covers, database, chart-freshness, incidenten, codecanaries, UI-status, backupstatus, recoveryrapport, operations-worker en recente fouten.

Aanvullend:

- `GET /api/ai/control-room/actions`
- `GET /api/ai/control-room/tasks`
- `GET /api/ai/control-room/changes`
- `POST /api/ai/control-room/telemetry`

## Veiligheidsgrenzen

- gedownloade audio blijft onwijzigbaar voor de AI;
- de UI kan geen systeemactie uitvoeren;
- geen vrije shell;
- geen externe netwerkresources vanuit AI-HTML;
- de autonome code-self-healer kan `ai_control_room.py`, `ai_ui_designer.py`, orchestratie-, learning-, database-, backup- en veiligheidsmodules niet herschrijven;
- functionele codepatches blijven de bestaande sandbox/test/backup/canary/rollback-keten gebruiken;
- UI-HTML staat in `/var/lib/top40-archiver/ai/control-room`, niet in de Git-checkout.

## Procesrechten

De 8041-service draait als `top40archiver`. De root recovery-worker gebruikt groep `top40archiver` en `UMask=0002`, zodat beide processen veilig dezelfde AI-memory/WAL-state en UI-telemetrie kunnen gebruiken zonder extra schrijfrechten naar downloads of de virtualenv.

## Installatiegedrag

De transactionele updater:

- maakt eerst de bestaande geverifieerde rollbackbackup;
- test ook `tests/test_ai_control_room.py`;
- valideert alle nieuwe 1.16.5-healthflags;
- controleert `/api/ai/control-room` en `/`;
- start na installatie direct `top40-ai-recovery.service`, zodat de lokale AI niet op de volgende vijfminutentick hoeft te wachten om zijn eerste Control Room-revisie te genereren.
