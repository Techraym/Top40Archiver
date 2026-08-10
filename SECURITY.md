# Securitybeleid

Meld beveiligingsproblemen niet als openbaar issue wanneer daarbij wachtwoorden, tokens, lokale paden of persoonsgegevens zichtbaar worden.

Gebruik waar mogelijk de private security-functie van GitHub.

## Nooit publiceren

Deel nooit:

- `SPOTIFY_CLIENT_SECRET`;
- Samba-wachtwoorden;
- persoonlijke browsercookies;
- inhoud van `/etc/top40-archiver.env`;
- productie-SQLite-databases;
- private API-tokens;
- credentials uit logs.

## Netwerk

Top40Archiver is ontworpen voor een vertrouwd lokaal netwerk.

Stel deze diensten niet rechtstreeks zonder aanvullende beveiligingslaag bloot aan internet:

```text
8040  hoofdapplicatie
8041  AI Control Room / Operator
8042  Log & AI Control
11434 Ollama
```

Poort 8042 en Ollama horen in het bijzonder lokaal/trusted bereikbaar te blijven. Ook de Samba-share mag niet rechtstreeks openbaar op internet worden aangeboden.

## AI-beveiligingsgrenzen

De lokale AI-laag is bedoeld als begrensde beheerlaag, niet als onbeperkte systeembeheerder.

Belangrijke grenzen:

- geen onbeperkte vrije shell;
- geen autonome verwijdering van gedownloade audio;
- geen autonoom overschrijven van bestaande audio;
- geen CAPTCHA-bypass;
- geen rate-limit-bypass;
- geen proxyrotatie als ontwijkingsmechanisme;
- geen gebruik van persoonlijke accounts/cookies als autonome workaround;
- menselijke HOLD/guidance moet prioriteit houden;
- veiligheidsbeleid mag niet autonoom worden versoepeld.

## Updates en codewijzigingen

Risicovolle updates of autonome codepromoties moeten gebruikmaken van de bestaande validatie-, backup-, canary- en rollbackmechanismen.

De hoofdapplicatie op poort 8040 moet beschikbaar blijven wanneer de afzonderlijke AI-laag problemen ondervindt.

## Audio

Gedownloade of reeds bestaande muziekbestanden zijn beschermde gebruikersdata.

Automatische beheer- of AI-acties mogen deze niet verwijderen om ruimte vrij te maken of bestaande bestanden stilzwijgend vervangen.
