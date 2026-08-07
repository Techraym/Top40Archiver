# Top40Archiver 1.16.7 — Runtime Convergence & Update Hygiene

## Doel

Versie 1.16.7 hardent de autonome runtime op basis van de eerste productie-uren van 1.16.6. De functionele AI-laag blijft hetzelfde concept volgen — autonome policy-gestuurde recovery met menselijke toezichtmogelijkheid — maar routinecycli worden sneller, systemd-statussen worden correcter geïnterpreteerd en actuele hitlijsten krijgen een kortere herstelroute.

De release is bedoeld als normale transactionele auto-update vanaf 1.16.6.

## Correcte systemd-semantiek voor oneshots

Timer-gestuurde `Type=oneshot` services zijn niet bedoeld om permanent actief te blijven. 1.16.7 maakt daarbij onderscheid tussen:

- een actieve/uitvoerende oneshot;
- normale stand-by met een gezonde gekoppelde timer;
- een eerdere mislukte uitvoering terwijl de gekoppelde timer nog actief is;
- een mislukte uitvoering zonder actieve automatische retry-route.

Een eerdere mislukte run met een gezonde timer is voortaan **attention** in plaats van **critical**. De mislukking blijft zichtbaar, maar veroorzaakt geen vals permanent service-incident. Wanneer ook de gekoppelde timer ontbreekt of inactief is, blijft de toestand terecht kritiek.

Dit voorkomt onder meer dat `top40-archiver-auto-update.service` na een eerdere mislukte updatecheck als blijvend defect wordt beschouwd terwijl `top40-archiver-auto-update.timer` al een volgende poging heeft gepland.

## Snellere Qwen-cycli

Lokale Qwen-analyse is ondersteunend aan de vaste policy-engine; een trage modelcall mag de deterministische monitoring niet minutenlang ophouden.

### Operations

- gezonde deterministische operations-cycli slaan de Qwen-call volledig over;
- Qwen wordt alleen ingezet wanneer er acties, aanbevelingen of daadwerkelijke aandachtspunten zijn;
- de modelcontext is compacter;
- de output is begrensd;
- de HTTP-timeout is 45 seconden;
- een timeout verandert een reeds uitgevoerde veilige policycontrole niet in een foutieve mutation.

### Service recovery

- wanneer na policy-acties geen kritieke service-afwijkingen overblijven, is geen modeldiagnose meer nodig;
- bij resterende afwijkingen krijgt Qwen maximaal 45 seconden en een korte outputbudget;
- een timeout wordt als niet-beschikbare aanvullende diagnose geregistreerd, terwijl de policy-uitkomst leidend blijft.

### Autonome code-repair

- foutbewijs voor het model is begrensd tot 16 kB;
- broncodecontext is begrensd tot 32 kB totaal en 14 kB per bestand;
- modelgeneratie krijgt maximaal 60 seconden en een begrensde output;
- een model-timeout of tijdelijke Ollama-fout wijzigt geen productiecode en maakt de complete recoverycyclus niet onnodig defect;
- bestaande sandboxvalidatie, geverifieerde versiebackup, tweede waarneming/canary en automatische rollback blijven vereist.

## Actuele Top 40 en Tipparade

De freshness-guard herstelt een achterlopende actuele editie sneller:

- retry-cooldown: 20 → 10 minuten;
- freshness-timer: iedere 30 → iedere 10 minuten na de vorige uitvoering;
- voor uitsluitend de nieuwste verwachte week wordt eerst de ongedateerde actuele Top40.nl-pagina geprobeerd;
- wanneer die nog een oude editie geeft, wordt daarna de expliciete `/jaar/week-N` bron geprobeerd;
- historische tussenweken blijven uitsluitend gericht en sequentieel opgehaald;
- een bron wordt pas opgeslagen wanneer de werkelijk gelezen jaar/week exact overeenkomt met de gevraagde editie;
- een mismatch wordt gelogd en nooit als verkeerde actuele editie opgeslagen.

Dit verkleint het venster waarin bijvoorbeeld de Tipparade al op de nieuwe week staat en de Top 40 nog op de vorige week staat, zonder de bronvalidatie te versoepelen.

## Git- en updater-hygiëne

De transactionele updater draait als root, terwijl de live repository eigendom kan zijn van de beheeraccount. Daardoor konden nieuwe objecten in `.git/objects` root-owned achterblijven, waarna een handmatige `git fetch` als beheerder mislukte.

1.16.7:

- registreert alleen `/opt/top40-archiver` als root `safe.directory` wanneer nodig;
- onthoudt eigenaar en groep van de repository;
- geeft `.git` op ieder updater-exitpad terug aan die repository-eigenaar;
- doet dit ook na rollback en na een geslaagde update;
- verandert niets aan de bestaande dirty-worktreecontrole: onbekende lokale wijzigingen blijven een update blokkeren;
- actieve, aantoonbare AI-canarypatches blijven volgens het bestaande handoff-contract behandeld.

## Beveiliging en databehoud

1.16.7 versoepelt geen veiligheidsgrens:

- gedownloade audio mag niet autonoom worden verwijderd;
- het model krijgt geen vrije shell;
- uitvoerbare herstelacties blijven via de bestaande allowlist/safe-action-laag lopen;
- AI-beheer-, veiligheids-, database- en updatebeleidbestanden blijven uitgesloten van autonome code-repair;
- een productiecode-canary vereist nog steeds sandboxtests en een geverifieerde rollbackbackup;
- operationele AI-uitkomsten blokkeren geen technisch gezonde softwarepromotie, maar blijven zichtbaar en worden door de runtime opnieuw beoordeeld;
- operator guidance en domein-holds blijven beschikbaar zonder menselijke goedkeuring per normale cyclus te vereisen.

## Releasevalidatie

De 1.16.7-update draait tijdens installatie de bestaande releasecontracttests plus regressietests voor:

- service-watchdog en timer/oneshot-semantiek;
- begrensde operations-modelanalyse;
- chart freshness en current-first/latest-week fallback;
- autonome code-repairpolicy en contextbudgetten;
- updatecontract, Git-eigendom, backups, AI Session en Control Room.

De lokaal geïnstalleerde commit-SHA wordt nog steeds pas gepromoveerd nadat de transactionele installatie en finale 8040/8041/8042-healthchecks zijn geslaagd.
