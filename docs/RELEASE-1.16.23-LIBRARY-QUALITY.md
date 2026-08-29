# Top40Archiver Library Quality 8085 — 1.16.23

Deze additieve update is gebouwd bovenop Top40Archiver commit
`609d299e8b5eb625f0c4ab6d5e67c1ca352befe2` (`Fix historical download matching`).

De update raakt de bestaande downloadmatching niet aan. Hij voegt uitsluitend de
Library Quality Engine op poort 8085 toe, inclusief SQLite kwaliteitsindex,
metadataherstel, covercontrole, technische audioanalyse, BPM/key, loudness,
Chromaprint fingerprint en radio-cueanalyse.

## Harde grenzen

- geen AerOn-verbinding;
- geen AerOn databasewrites of push;
- geen dry-run;
- geen audio-hercodering tijdens metadatareparatie;
- bestaande goede tags worden niet blind overschreven;
- eerste volledige scan start niet tijdens installatie.

## GitHub transport

Het releasepakket is opgeslagen als 13 gewone UTF-8/base64-tekstsegmenten. De
installer voegt deze lokaal samen, decodeert ze naar het TAR.GZ-pakket en controleert
daarna SHA-256 `1487c41ba019ddf8273063ef14bf9f5971dd2ae381e9dbe33d48db5c62d6f60c`
voordat er iets wordt geïnstalleerd.

De installer controleert bovendien dat `/var/lib/top40-archiver/update-state/installed_commit_sha`
og exact de geteste basiscommit `609d299e...` bevat. Daardoor kan deze patch een
latere core-update niet stilzwijgend overschrijven.
