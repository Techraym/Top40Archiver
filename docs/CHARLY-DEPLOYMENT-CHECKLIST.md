# CHARLY deployment checklist

Voor het mergen/deployen van Top40Archiver 1.16.23:

1. GitHub Actions moet volledig groen zijn.
2. `tests/test_charly_integration_contract.py` moet de vendored CHARLY v0.2.0-bron exact valideren.
3. Op de NUC moet vóór installatie voldoende vrije ruimte aanwezig zijn voor `/opt/charly`, `/var/lib/charly` en de rollbackbackup.
4. `ollama.service` moet vooraf gezond zijn op de bestaande configuratie.
5. `scripts/install-1.16.23.sh` voert eerst de bestaande Top40Archiver transactionele update uit en daarna pas de CHARLY-integratie.
6. CHARLY neemt `127.0.0.1:11434` over; de private Ollama/Qwen-backend verhuist naar `127.0.0.1:11435`.
7. Na migratie moeten `:8765/api/health`, `:11434/api/version`, `:11435/api/version` en `:8041/healthz` reageren.
8. Bij een CHARLY/Ollama-migratiefout moet `scripts/install-charly-top40.sh` zijn eigen rollback uitvoeren.
9. De muziekbibliotheek `/mnt/top40-music` wordt door de CHARLY-installer niet aangeraakt.
10. Externe AI-providers blijven optioneel; zonder credentials moet lokale Qwen/Ollama functioneren.
