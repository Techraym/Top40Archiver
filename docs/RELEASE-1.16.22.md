# Top40Archiver 1.16.22

Releasedatum: 10 augustus 2026.

## Doel

Versie 1.16.22 synchroniseert de officiële GitHub-repository met de gevalideerde productiecode die op de Top40Archiver-NUC draaide.

De release bouwt voort op 1.16.20 en behoudt de bestaande release-infrastructuur, installers, tests en systemd-configuratie.

## Downloadactiviteit

De hoofdinterface geeft meer inzicht in actieve downloads en actuele downloadstatus.

De zelfstandige `top40-download-manager.service` blijft verantwoordelijk voor de persistente downloadqueue.

## Matching

De matchinglogica is verder aangescherpt om providerresultaten betrouwbaarder te koppelen aan de gewenste artiest/titelcombinatie.

Versiecontrole en bestaande audiovalidatie blijven onderdeel van de pipeline.

## Downloadconcurrency

De dynamische concurrencylaag is bijgewerkt. Globale concurrency en provider-specifieke grenzen blijven gescheiden.

## Albumhoezen

De cover-art verwerking bevat aanvullende matching- en verwerkingsverbeteringen. De coverworker blijft los van de hoofdwebapplicatie draaien.

## AI UI

Nieuwe modules:

```text
app/ai_ui_css_designer.py
app/ai_ui_theme_designer.py
```

Daarnaast zijn de bestaande AI UI-designer en legacy-designer bijgewerkt.

De AI-beheerlaag blijft gescheiden van de hoofdapplicatie.

## Hoofddashboard

HTML, CSS en JavaScript van de hoofdinterface zijn bijgewerkt, waaronder de weergave van actuele downloadactiviteit.

De browser-assets gebruiken een nieuwe cacheversie zodat clients de actuele bestanden laden.

## Updatecompatibiliteit

Nieuw:

```text
scripts/install-1.16.22.sh
```

De installer blijft gekoppeld aan de bestaande gevalideerde legacy bootstrap-/rollbackketen.

## Veiligheid

Bestaande veiligheidsgrenzen blijven gelden:

- geen autonome verwijdering van gedownloade audio;
- geen overschrijven van bestaande audio;
- geen CAPTCHA-bypass;
- geen proxyrotatie of rate-limit-bypass;
- geen onbeperkte AI-shell;
- officiële updates behouden backup-/rollbackcontrole.

## Validatie

De release is vóór publicatie getest vanuit een aparte Git-worktree gebaseerd op GitHub `main`.

Resultaat:

```text
257 passed
```

Python syntaxcontrole:

```text
0 fouten
```

Releasecommit:

```text
e8e6dc6
```

Daarna zijn de actuele README's en changelog-documentatie bijgewerkt. Historische `docs/RELEASE-1.16.x.md`-bestanden blijven ongewijzigd omdat zij hun eigen release documenteren.
