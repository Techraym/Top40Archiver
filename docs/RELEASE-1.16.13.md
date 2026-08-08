# Top40Archiver 1.16.13

## Autonomous recovery convergence + Qwen Operator Chat

Deze release maakt de herstelarchitectuur aantoonbaar consistenter met de Multi Source Download Engine en voegt een veilige operatorchat toe op poort 8041.

### Qwen Operator Chat

Nieuwe routes:

- `/operator-chat`
- `/ai-chat`
- `POST /api/ai/operator-chat`
- `GET /api/ai/operator-chat/status`

De operator kan een opdracht plakken die bijvoorbeeld samen met ChatGPT is opgesteld. Er zijn twee modi:

- `diagnose`: Qwen analyseert lokale evidence en voert geen mutaties uit;
- `repair`: Qwen mag alleen acties voorstellen uit een vaste whitelist. Iedere voorgestelde actie wordt daarna opnieuw door deterministische evidence-policy gecontroleerd voordat `/usr/local/sbin/top40-safe-action` wordt aangeroepen.

De chat heeft geen vrije shell. Audio verwijderen of overschrijven, cookie/CAPTCHA/rate-limit bypass en proxyrotatie blijven verboden.

### Download recovery

`app.ai_recovery` werkt nu rechtstreeks met `download_jobs` via `retry_job()` in plaats van alleen de legacy `tracks.download_status` te resetten.

Belangrijke gedragswijzigingen:

- gewone retrybatches herstarten `top40-download-manager.service` niet meer;
- `waiting_retry` voor tijdelijke provider-/netwerkfouten blijft onder het backoffbeleid van de downloadmanager;
- stale actieve jobs kunnen opnieuw worden gequeued zonder de gezonde manager te onderbreken;
- legacy `download_workers`-mutatie is uit de recoverylus verwijderd;
- rapportage vermeldt expliciet dat `download_jobs` wordt gebruikt en dat geen managerrestart is aangevraagd.

### Operations worker

De operations-worker bewaakt nu de actuele service `top40-download-manager.service` in plaats van de oude `top40-archiver-download.service`.

### Safe action uitbreidingen

Nieuwe begrensde acties:

- `run_ai_recovery`
- `run_provider_ai`

Deze starten uitsluitend bestaande systemd-services en geven Qwen geen algemene shelltoegang.

### Veiligheid

Ongewijzigde harde regels:

- geen gedownloade audio verwijderen;
- geen bestaande audio overschrijven;
- versiepromotie blijft via geverifieerde backup/rollback;
- geen persoonlijke provideraccounts/cookies;
- geen CAPTCHA- of rate-limit-omzeiling;
- geen proxyrotatie;
- geen onbeperkte AI-shell.
