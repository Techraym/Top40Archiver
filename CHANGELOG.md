# Changelog

Alle noemenswaardige wijzigingen worden in dit bestand bijgehouden.

## [1.7.0] - 2026-08-03

### Toegevoegd

- Actuele en historische Nederlandse Top 40.
- Actuele en historische Tipparade.
- Permanente deduplicatie met SQLite.
- Spotify uitsluitend als metadata-controle.
- YouTube-zoekselectie en MP3-download via yt-dlp en FFmpeg.
- Opslag als `Genre/beginletter/Artiest - Titel.mp3`.
- Hervatbare historische import vanaf 1965 en 1967.
- Compact live dashboard met FastAPI.
- Systemd-services en timers voor actuele en historische controles.
- Externe opslag via Samba beschikbaar maken voor Windows.
- Directe update vanaf GitHub met `update-from-github.sh`.

### Belangrijk

- De database blijft leidend wanneer MP3-bestanden van de externe schijf worden verwijderd.
- Een eenmaal succesvol verwerkt nummer wordt niet opnieuw gedownload.
