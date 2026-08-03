# Updaten vanaf GitHub en Samba instellen

Deze instructies zijn bedoeld voor een bestaande installatie op Debian 13.

## 1. Inloggen en root worden

```bash
ssh top40@<IP-VAN-DE-NUC>
su -
```

## 2. Eenmalig updaten naar de versie met automatische updates

Download het updatescript, maak het uitvoerbaar en start het:

```bash
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh

chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

Het script:

1. haalt de actuele commit-SHA van `main` op via GitHub;
2. controleert dat dit een geldige SHA van 40 hexadecimale tekens is;
3. downloadt de broncode via die exacte, vastgepinde commit-SHA;
4. berekent de SHA-256 van het gedownloade ZIP-archief;
5. voert `update-existing.sh` uit;
6. controleert na afloop dat de lokaal geregistreerde SHA gelijk is aan de verwachte GitHub-SHA.

De update behoudt:

- `/var/lib/top40-archiver/top40.sqlite3`;
- instellingen;
- historische cursors;
- permanente downloadstatussen;
- de externe muziekopslag.

## 3. Automatische updates

Na installatie is deze timer actief:

```text
top40-archiver-auto-update.timer
```

De controle draait:

- twee minuten na iedere systeemstart;
- daarna iedere 24 uur;
- ook na een gemiste uitvoering dankzij `Persistent=true`.

Controleer de timer:

```bash
systemctl status top40-archiver-auto-update.timer --no-pager
systemctl list-timers --all | grep top40-archiver-auto-update
```

Handmatig controleren:

```bash
systemctl start top40-archiver-auto-update.service
journalctl -u top40-archiver-auto-update.service -n 100 --no-pager
```

Een geforceerde controle en herinstallatie van de actuele GitHub-commit:

```bash
/opt/top40-archiver/auto-update.sh --force
```

Updategegevens worden bewaard in:

```text
/var/lib/top40-archiver/update-state/installed_commit_sha
/var/lib/top40-archiver/update-state/last_remote_commit_sha
/var/lib/top40-archiver/update-state/last_archive_sha256
/var/lib/top40-archiver/update-state/last_check
/var/lib/top40-archiver/update-state/last_success
```

Bekijken:

```bash
for file in /var/lib/top40-archiver/update-state/*; do
  printf '%s: ' "$(basename "$file")"
  cat "$file"
done
```

De geïnstalleerde commit-SHA wordt pas gewijzigd nadat de volledige update is geslaagd. Bij een fout blijft de vorige SHA geregistreerd en is de fout zichtbaar in het systemd-log.

## 4. Spotify-controle instellen

```bash
nano /etc/top40-archiver.env
```

```text
SPOTIFY_CLIENT_ID=jouw_client_id
SPOTIFY_CLIENT_SECRET=jouw_client_secret
SPOTIFY_MARKET=NL
```

Daarna:

```bash
systemctl restart top40-archiver-web.service
```

## 5. Samba eenmalig instellen of opnieuw configureren

Controleer eerst of de externe schijf werkelijk is gekoppeld:

```bash
findmnt /mnt/top40-music
runuser -u top40archiver -- test -w /mnt/top40-music && echo "Schrijven werkt"
```

Start vervolgens:

```bash
/opt/top40-archiver/setup-network-share.sh
```

Het script vraagt om een Samba-wachtwoord voor Linux-gebruiker `top40`.

Windows-pad:

```text
\\Top40\Top40Music
```

Of:

```text
\\<IP-VAN-DE-NUC>\Top40Music
```

## 6. Alles controleren

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-check.timer --no-pager
systemctl status top40-archiver-history.timer --no-pager
systemctl status top40-archiver-auto-update.timer --no-pager
systemctl status smbd.service --no-pager
findmnt /mnt/top40-music
```

Open het dashboard:

```text
http://<IP-VAN-DE-NUC>:8040
```

## Belangrijk bij het leeghalen van de schijf

MP3-bestanden mogen via Windows worden gekopieerd en daarna van de externe schijf worden verwijderd. De SQLite-database blijft op de interne systeemschijf leidend. Tracks die al status `downloaded` hebben, worden niet opnieuw gedownload omdat het bestand ontbreekt.
