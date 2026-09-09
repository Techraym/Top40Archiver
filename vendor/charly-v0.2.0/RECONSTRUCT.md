# CHARLY v0.2.0 vendored source

De acht `part-*.b64` bestanden vormen samen één base64-gecodeerde `tar.gz` met de native CHARLY v0.2.0-broncode.

De integratietest `tests/test_charly_integration_contract.py` controleert vóór release:

- exact acht delen (`part-00.b64` t/m `part-07.b64`);
- SHA-256 van de samengevoegde base64-data;
- SHA-256 van het gedecodeerde archief;
- geldige gzip/tar-structuur;
- aanwezigheid van agent, router, Ollama-gateway, native Debian-installer en systemd-units.

De installatie wordt uitgevoerd door `scripts/install-charly-top40.sh`. Deze reconstrueert en valideert het pakket opnieuw voordat er iets aan de actieve Ollama/CHARLY-services wordt gewijzigd.
