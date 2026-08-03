# Updaten vanaf GitHub en Samba instellen

Deze instructies zijn bedoeld voor een bestaande installatie op Debian 13.

## 1. Inloggen en root worden

```bash
ssh top40@<IP-VAN-DE-NUC>
su -
```

## 2. Updaten vanaf GitHub

Download het updatescript eerst lokaal, controleer het desgewenst en voer het daarna uit:

```bash
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh

chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

Het script downloadt de nieuwste `main`-versie, voert `update-existing.sh` uit en behoudt:

- `/var/lib/top40-archiver/top40.sqlite3`;
- instellingen;
- historische cursors;
- permanente downloadstatussen;
- de externe muziekopslag.

## 3. Spotify-controle instellen

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

## 4. Samba eenmalig instellen of opnieuw configureren

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

## 5. Controleren

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-check.timer --no-pager
systemctl status top40-archiver-history.timer --no-pager
systemctl status smbd.service --no-pager
findmnt /mnt/top40-music
```

Open het dashboard:

```text
http://<IP-VAN-DE-NUC>:8040
```

## Belangrijk bij het leeghalen van de schijf

MP3-bestanden mogen via Windows worden gekopieerd en daarna van de externe schijf worden verwijderd. De SQLite-database blijft op de interne systeemschijf leidend. Tracks die al status `downloaded` hebben, worden niet opnieuw gedownload omdat het bestand ontbreekt.
