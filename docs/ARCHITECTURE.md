# Architectuur

## Datastroom

```text
Top 40 / Tipparade bron
        ↓
Normalisatie artiest + titel
        ↓
SQLite deduplicatie
        ↓
Spotify metadata-controle (optioneel)
        ↓
YouTube-resultaat selecteren
        ↓
yt-dlp + FFmpeg op tijdelijke interne opslag
        ↓
Definitieve MP3 naar externe opslag
```

## Leidende database

De database staat standaard op:

```text
/var/lib/top40-archiver/top40.sqlite3
```

Een track met status `downloaded` blijft verwerkt wanneer de MP3 later wordt verplaatst of verwijderd. De aanwezigheid van een bestand op de externe opslag is geen criterium voor een nieuwe download.

## Opslag

```text
/mnt/top40-music/Top40/<Genre>/<A-Z, cijfer of teken>/<Artiest - Titel.mp3>
```

Tijdelijke downloads en conversies horen op de interne Linux-schijf:

```text
/var/lib/top40-archiver/download-temp
```

## Processen

- `top40-archiver-web.service`: FastAPI-dashboard.
- `top40-archiver-check.service`: actuele Top 40 en Tipparade.
- `top40-archiver-check.timer`: wekelijkse actuele controle.
- `top40-archiver-history.service`: historische batch.
- `top40-archiver-history.timer`: periodieke historische batch.
- `smbd.service`: Windows-netwerkschijf.
