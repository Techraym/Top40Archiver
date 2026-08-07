# Top40Archiver 1.16.6 — Autonomous Qwen AI Session + Operator Guidance

## Doel

Naast de AI Control Room op poort 8041 heeft Top40Archiver nu een vaste menselijke toezichtpagina:

- `http://<host>:8041/ai-session`

De lokale Ollama/Qwen-assistent blijft autonoom werken. Menselijke input is niet nodig voor normale cycli. De operator kan de werkstroom wel live volgen en alleen ingrijpen wanneer dat nodig is.

## AI Session

De Session toont een doorlopende, chat-achtige werklog van de echte autonome recovery/learning-cyclus. Per fase wordt zichtbaar:

1. welke controle Qwen/het AI-platform uitvoert;
2. welk domein wordt beoordeeld;
3. een korte auditbare beslissamenvatting;
4. welke begrensde actie is uitgevoerd;
5. het verificatieresultaat;
6. het leer-/canaryresultaat;
7. het einde van de autonome cyclus.

De pagina toont bewust geen verborgen token-voor-token chain-of-thought. Wel worden voldoende observaties, beslissamenvattingen, acties, resultaten en technische details opgeslagen om menselijk toezicht mogelijk te maken.

## Geen input vereist

De vijfminutencyclus blijft zelfstandig draaien. Iedere cyclus meldt onder meer services, opslag, chart freshness, operations, downloads, codeherstel, codeverbetering en Control Room UI-verificatie in de Session.

Er is geen menselijke goedkeuring per cyclus of per normale veilige herstelactie nodig.

## Operator Guidance

Onderaan de Session kan de menselijke operator optioneel een blijvende correctie typen. De operator kiest het toepassingsgebied:

- alles;
- operations;
- downloads;
- covers;
- charts;
- services;
- opslag;
- code;
- 8041 UI.

Een normale `guidance` stuurt de lokale AI bij binnen de bestaande harde veiligheidsgrenzen. De richtlijn blijft actief totdat de operator hem expliciet beëindigt.

Na het versturen geeft de lokale `qwen3:4b` direct een korte bevestiging van wat hij heeft begrepen en hoe de richtlijn zijn volgende autonome beoordelingen beïnvloedt. De opgeslagen regel wordt daarna opnieuw aan relevante Qwen-prompts aangeboden.

## Operator Hold

Met **Pauzeer domein** kan de operator nieuwe autonome mutaties in één domein blokkeren zonder monitoring stil te leggen.

Werkelijke holds bestaan voor:

- downloads;
- services;
- storage;
- charts;
- operations;
- covers;
- code;
- Control Room UI.

Een globale hold geldt voor alle domeinen.

Tijdens een hold blijft de actuele toestand zichtbaar. Reeds actieve code- of UI-canaries mogen nog worden geverifieerd en bij regressie automatisch worden teruggerold; een menselijke hold mag herstel van een reeds gepromoveerde slechte canary niet blokkeren.

## Vaste menselijke toezichtlaag

De AI Session is policy-code en wordt niet door de autonome UI-designer herschreven. Ook de autonome code-repair worker mag `app/ai_session_console.py` niet aanpassen.

Daarmee kan Qwen de Control Room op `/` verder optimaliseren, maar niet de pagina waarmee de mens Qwen controleert.

## Beveiliging

De bestaande veiligheidsgrenzen blijven gelden:

- geen vrije shell voor het model;
- uitvoerbare acties uitsluitend via de bestaande whitelist/safe-action-laag;
- geen autonome versoepeling van veiligheids-, backup- of updatebeleid;
- gedownloade audio blijft beschermd;
- autonome codepatches alleen na sandboxtests, geverifieerde backup en canary;
- operatorrichtlijnen kunnen veiligheidsgrenzen sturen maar nooit versoepelen;
- de Session toont beslissamenvattingen, niet verborgen model-chain-of-thought.

## Data en audit

Nieuwe tabellen in `ai_memory.sqlite`:

- `ai_session_event` — chronologische werklog;
- `operator_guidance` — actieve en afgesloten menselijke richtlijnen/holds.

Technische Session-events bewaren slechts een begrensde rapportpreview. De volledige operationele rapporten blijven via de Control Room en bestaande AI-statebestanden beschikbaar, zodat de chatdatabase niet onbeperkt groeit door duplicatie.

## API

- `GET /api/ai/session/status`
- `GET /api/ai/session/events`
- `GET /api/ai/session/guidance`
- `POST /api/ai/session/guidance`
- `POST /api/ai/session/guidance/{id}/close`
- `GET /ai-session`

## Releasevalidatie

De transactionele updater controleert de Session-status, eventfeed en pagina naast de bestaande 8040/8041/8042-healthchecks. De releasecontracttests bewaken daarnaast dat alle in de UI aangeboden holds werkelijk een mutation guard hebben en dat de menselijke toezichtmodule niet autonoom herschrijfbaar is.
