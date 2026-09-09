# CHARLY operations

Na installatie:

```bash
systemctl status charly-core.service --no-pager
systemctl status charly-ollama-gateway.service --no-pager
systemctl status ollama.service --no-pager
curl -fsS http://127.0.0.1:8765/api/health
curl -fsS http://127.0.0.1:11434/api/version
curl -fsS http://127.0.0.1:11435/api/version
curl -fsS http://127.0.0.1:8041/healthz
```

De bestaande Top40Archiver-calls blijven `127.0.0.1:11434` gebruiken. Rechtstreekse modelbackenddiagnostiek gebruikt alleen voor beheer `127.0.0.1:11435`.

Bij problemen tijdens de eerste migratie is de rollbackbackup te vinden onder `/var/lib/top40-archiver/backups/charly-install/`.
