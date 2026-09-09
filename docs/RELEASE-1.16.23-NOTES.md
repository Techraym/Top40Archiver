# Release notes — Top40Archiver 1.16.23 / CHARLY

Deze release introduceert CHARLY als native centrale AI-orchestrator op de bestaande Debian NUC.

## Gedrag

- bestaande Top40Archiver-AI en Qwen/Ollama-calls behouden poort `11434`;
- CHARLY wordt transparante gateway op `11434`;
- Ollama/Qwen draait als private backend op `11435`;
- CHARLY Core/API gebruikt `8765`;
- bestaande Top40 download-, recovery-, operator- en veiligheidslogica blijft leidend;
- machine-AI krijgt geen speelse CHARLY-persoonlijkheid in JSON/diagnosecontracten;
- externe resources zijn optioneel en lokale verwerking blijft fallback;
- installatie is native, zonder Docker of extra VM.

De poortmigratie is bewust onderdeel van een featurebranch/PR en wordt niet rechtstreeks op `main` gezet voordat CI en de releasechecks groen zijn.
