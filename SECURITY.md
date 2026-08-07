# Securitybeleid

Meld kwetsbaarheden niet als openbaar issue wanneer daarbij wachtwoorden, tokens, lokale paden of persoonsgegevens zichtbaar worden.

Stuur een private melding via de beveiligingsfunctie van GitHub wanneer die voor deze repository beschikbaar is. Deel nooit:

- `SPOTIFY_CLIENT_SECRET`;
- Samba-wachtwoorden;
- browsercookies;
- inhoud van `/etc/top40-archiver.env`;
- een productie-SQLite-database met niet-openbare gegevens.

De applicatie is bedoeld voor een vertrouwd lokaal netwerk. Publiceer poort `8040` of de Samba-share niet rechtstreeks op internet.
