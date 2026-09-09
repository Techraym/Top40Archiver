# CHARLY v0.2.0 vendored source

De acht `part-*.b64` bestanden vormen samen één base64-gecodeerde `tar.gz` met de native CHARLY v0.2.0-broncode.

De integratietest `tests/test_charly_integration_contract.py` controleert vóór release:

- exact acht delen (`part-00.b64` t/m `part-07.b64`);
- geldige base64 na het negeren van tekstuele whitespace/regelafbreking;
- SHA-256 van het gedecodeerde release-archief;
- geldige gzip/tar-structuur;
- aanwezigheid van agent, router, Ollama-gateway, native Debian-installer en systemd-units.

De installatie wordt uitgevoerd door `scripts/install-charly-top40.sh`. Deze reconstrueert en valideert het pakket opnieuw voordat er iets aan de actieve Ollama/CHARLY-services wordt gewijzigd. De SHA-256 van het gedecodeerde archief is de release-identiteit; de precieze regelopmaak van de base64-transportbestanden is dat niet.
