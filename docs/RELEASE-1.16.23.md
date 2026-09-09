# Top40Archiver 1.16.23 — CHARLY AI Orchestrator

Release 1.16.23 introduceert **CHARLY v0.2.0** als centrale AI-orchestrator op de bestaande Debian NUC.

## Kernwijziging

Alle bestaande Ollama/Qwen-inference op de standaard lokale Ollama-poort loopt voortaan transparant via CHARLY:

```text
voorheen: Top40Archiver -> Ollama/Qwen :11434
nu:      Top40Archiver -> CHARLY :11434 -> lokale Qwen :11435 / externe resource
```

Bestaande Top40Archiver-callers hoeven hierdoor niet tegelijk herschreven te worden. Qwen blijft beschikbaar als lokale fallback/provider, terwijl CHARLY routing, prioritering, audit, context en toekomstige externe delegatie centraal kan beheren.

## Native NUC-installatie

CHARLY wordt rechtstreeks op Debian geïnstalleerd:

- geen Docker;
- geen extra VM;
- applicatie onder `/opt/charly`;
- configuratie onder `/etc/charly`;
- runtime/geheugen onder `/var/lib/charly`;
- beheer via systemd.

## Poorten

```text
8040   Top40Archiver hoofdapp
8041   Top40Archiver AI Control Room
8042   Log & AI Control
8765   CHARLY Core / API / gezicht
11434  CHARLY Ollama-compatible gateway
11435  private Ollama/Qwen backend
```

## Compatibiliteit

CHARLY ondersteunt de voor Top40Archiver relevante Ollama-compatibiliteitsroutes, waaronder `/api/generate` en `/api/chat`. Niet-inference modelroutes blijven via de gateway beschikbaar op de vertrouwde poort 11434 en worden naar de private Ollama-backend doorgestuurd.

Daarnaast biedt CHARLY een OpenAI-compatible `/v1/chat/completions` endpoint voor toekomstige NUC-services.

## Routing en capaciteit

CHARLY kan taken indelen als LOCAL, ONLINE, HYBRID of DELEGATE en heeft een prioriteitsqueue met REALTIME, HIGH, NORMAL en BATCH. Externe AI-resources zijn optioneel. Als geen externe provider is ingesteld, blijft lokaal Ollama/Qwen beschikbaar.

Doel van deze architectuur is minimale lokale systeembelasting met maximale effectieve AI-capaciteit.

## Veiligheid

De bestaande Top40Archiver-veiligheidsgrenzen blijven leidend:

- geen vrije shell voor AI;
- geen autonome verwijdering of overschrijving van bestaande audio;
- bestaande download-/matching-/validatiepolicy blijft intact;
- gevoelige gegevens worden standaard niet extern verwerkt;
- serviceacties blijven allowlisted en auditeerbaar;
- installatiefouten herstellen de eerdere CHARLY/Ollama-configuratie;
- de CHARLY-installatie raakt `/mnt/top40-music` niet aan.

## Updatepad

Release-updates gebruiken `scripts/install-1.16.23.sh`. Deze voert eerst het bestaande bewezen Top40Archiver transactionele updatepad uit en installeert daarna CHARLY via `scripts/install-charly-top40.sh`.

De CHARLY-bronrelease is gecontroleerd opgeslagen onder `vendor/charly-v0.2.0`. De installer reconstrueert deze delen en controleert de bron met SHA-256 voordat installatie plaatsvindt.

## Validatie vóór merge

De repositorytest voor CHARLY controleert onder andere:

- releaseversie en installercontract;
- shellsyntax van de nieuwe installers;
- aantal en volgorde van de vendored bron-delen;
- SHA-256 van de base64-bron;
- SHA-256 van de gereconstrueerde tarball;
- aanwezigheid van agent-, gateway- en native installatiemodules in het bronpakket;
- expliciete poortscheiding 11434/11435;
- expliciete bescherming van de muziekbibliotheek.
