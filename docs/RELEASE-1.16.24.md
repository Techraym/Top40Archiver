# Top40Archiver 1.16.24 — CHARLY autonomous recovery control

CHARLY is vanaf deze release niet alleen de AI-gateway maar ook de operationele controlelaag voor download-recovery.

- Nieuwe en actuele Top40/Tipparade-downloads houden altijd voorrang.
- CHARLY gebruikt maximaal één achtergrondslot voor hardnekkige recovery.
- Na herhaalde normale mislukkingen maakt CHARLY/Qwen zelfstandig nieuwe zoekstrategieën.
- Eerdere AI-zoektermen worden onthouden zodat dezelfde strategie niet eindeloos wordt herhaald.
- Een recoverycyclus is begrensd op maximaal 5 AI-rondes, 3 rondes zonder nieuwe evidence en 2 uur wandkloktijd.
- Na uitputting wordt een track geparkeerd met oplopende cooldown en later automatisch opnieuw beoordeeld.
- De retrytijd is adaptief; er bestaat geen vaste 30-secondenlus.
- Qwen-recovery wordt als `BATCH` naar de CHARLY-gateway gestuurd zodat interactieve AI voorrang houdt.

CHARLY mag uitsluitend de zoekstrategie wijzigen. De bestaande matcher, scoregrenzen, providerregels, audio-validatie en create-only opslag blijven beslissen of een kandidaat daadwerkelijk wordt geaccepteerd. Bestaande audio wordt niet overschreven en een lage score wordt nooit door AI geforceerd.

De normale keten wordt:

`mislukking -> automatische analyse -> nieuwe strategie -> retry -> verificatie -> eventueel parkeren -> automatische herbeoordeling`

Menselijke input is niet nodig voor normale dode links, slechte matches of uitgeputte providerresultaten.
