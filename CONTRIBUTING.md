# Bijdragen

Bijdragen zijn welkom via een issue of pull request.

## Ontwikkelomgeving

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pytest
```

## Richtlijnen

- Voeg voor functionele wijzigingen tests toe.
- Leg databasewijzigingen migratieveilig vast; bestaande databases mogen niet worden gewist.
- Sla nooit Spotify-geheimen, cookies, databases of gedownloade media in Git op.
- Behoud de kernregel dat SQLite leidend is en ontbrekende MP3-bestanden geen herdownload veroorzaken.
- Houd installatie en update compatibel met Debian 13 en systemd.
