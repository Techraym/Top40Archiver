# CHARLY v0.2.0 vendored source

Deze map bevat de gevalideerde CHARLY v0.2.0 bronrelease die Top40Archiver op de Debian NUC native installeert onder `/opt/charly`.

De tarball is als genummerde base64-delen opgeslagen omdat de GitHub-integratie alleen UTF-8 tekstbestanden schrijft. `scripts/install-charly-top40.sh` reconstrueert de delen in lexicografische volgorde, controleert zowel de base64-bron als de uitgepakte tarball met SHA-256 en voert daarna de native CHARLY-installer uit.

Verwachte bestanden:

```text
part-00.b64 ... part-07.b64
SHA256SUMS
```

De installatie gebruikt geen Docker en geen aparte VM. Bestaande CHARLY-configuratie onder `/etc/charly` wordt door de CHARLY-installer behouden. De Top40Archiver-wrapper maakt daarnaast een rollbackkopie van de bestaande CHARLY/Ollama-integratie voordat poorten of systemd-configuratie worden gewijzigd.

De muziekbibliotheek onder `/mnt/top40-music` wordt door deze installatie niet aangeraakt.
