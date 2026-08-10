# Updaten vanaf GitHub en Samba instellen

Deze instructies gelden voor een bestaande Top40Archiver-installatie op Debian 13.

## Update vanaf GitHub

Inloggen:

```bash
ssh top40@<IP-VAN-DE-NUC>
```

Root worden:

```bash
su -
```

Actuele updater ophalen:

```bash
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh

chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

De updater gebruikt GitHub `main` als officiële releasebron.

## Release 1.16.22

De repository bevat voor deze release:

```text
scripts/install-1.16.22.sh
```

Deze bootstrap behoudt de bestaande transactionele update-/rollbackketen.

## Gegevens die behouden blijven

Een normale update hoort de volgende productiegegevens niet te vervangen:

```text
/var/lib/top40-archiver/top40.sqlite3
/var/lib/top40-archiver/ai_memory.sqlite
/mnt/top40-music/Top40
```

Ook lokale configuratie, historische voortgang en update-state blijven behouden.

## Automatische updates

Timer:

```text
top40-archiver-auto-update.timer
```

Status:

```bash
systemctl status top40-archiver-auto-update.timer --no-pager
systemctl list-timers --all | grep top40-archiver-auto-update
```

Log:

```bash
journalctl -u top40-archiver-auto-update.service -n 100 --no-pager
```

Handmatig controleren:

```bash
systemctl start top40-archiver-auto-update.service
```

Geforceerd de actuele GitHub-commit opnieuw installeren:

```bash
/opt/top40-archiver/auto-update.sh --force
```

## Update-state

Updategegevens worden bewaard onder:

```text
/var/lib/top40-archiver/update-state/
```

Daar kunnen onder andere commit-SHA's, checksums en laatste controle-/updatemomenten worden geregistreerd.

## Services controleren

Na een update:

```bash
systemctl is-active top40-archiver-web.service
systemctl is-active top40-archiver-ai.service
systemctl is-active top40-download-manager.service
systemctl is-active top40-log-reader.service
systemctl is-active top40-archiver-cover-art.service
systemctl is-active ollama.service
```

Poorten controleren:

```bash
ss -ltnp | grep -E ':8040|:8041|:8042|:11434'
```

Interfaces:

```text
http://<IP-VAN-DE-NUC>:8040
http://<IP-VAN-DE-NUC>:8041
```

Poort 8042 en Ollama horen lokaal/trusted te blijven.

## Spotify metadata

Configuratie:

```bash
nano /etc/top40-archiver.env
```

Bijvoorbeeld:

```text
SPOTIFY_CLIENT_ID=jouw_client_id
SPOTIFY_CLIENT_SECRET=jouw_client_secret
SPOTIFY_MARKET=NL
```

Daarna:

```bash
systemctl restart top40-archiver-web.service
```

## Samba

Controleer de externe opslag:

```bash
findmnt /mnt/top40-music
runuser -u top40archiver -- test -w /mnt/top40-music && echo "Schrijven werkt"
```

Configureren:

```bash
/opt/top40-archiver/setup-network-share.sh
```

Windows-pad:

```text
\\Top40\Top40Music
```

of:

```text
\\<IP-VAN-DE-NUC>\Top40Music
```

## Belangrijk

De SQLite-database blijft leidend voor reeds verwerkte tracks. Wanneer een reeds gedownload audiobestand handmatig van de externe schijf wordt verwijderd, betekent dat niet automatisch dat Top40Archiver het opnieuw downloadt.

Maak vóór handmatige databasewijzigingen altijd een afzonderlijke databasebackup.
