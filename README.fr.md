# Top40Archiver

[Nederlands](README.md) · [English](README.en.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

[![Tests](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml/badge.svg)](https://github.com/Techraym/Top40Archiver/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Debian 13](https://img.shields.io/badge/Debian-13-red.svg)](https://www.debian.org/)

Top40Archiver construit automatiquement sous Debian une archive musicale locale à partir du **Top 40 néerlandais et de la Tipparade**. SQLite reste la source d’administration principale : lorsqu’un titre a déjà été traité avec succès, il n’est pas téléchargé de nouveau simplement parce que le fichier audio a ensuite été déplacé ou supprimé.

**Version actuelle : 1.16.22**

## Architecture principale

```text
Top 40 + Tipparade
        ↓
normalisation artiste + titre
        ↓
déduplication SQLite
        ↓
enrichissement facultatif des métadonnées
        ↓
file de téléchargement persistante
        ↓
Multi Source Download Engine
        ↓
correspondance des candidats + contrôle de version
        ↓
validation FFprobe / FFmpeg
        ↓
stockage audio définitif
        ↓
traitement des pochettes
```

L’application web n’exécute pas elle-même les téléchargements externes de longue durée. Les tâches sont placées dans une file persistante et traitées par le gestionnaire de téléchargement autonome.

## Fonctions principales

- Top 40 et Tipparade actuels ;
- historique du Top 40 depuis `1965-W01` ;
- historique de la Tipparade depuis `1967-W28` ;
- imports historiques reprenables ;
- contrôle automatique de fraîcheur des classements actuels ;
- file de téléchargement centrale persistante ;
- service autonome `top40-download-manager.service` ;
- concurrence de téléchargement dynamique et limitée ;
- pacing, état de santé, cooldowns et circuit breakers propres à chaque fournisseur ;
- correspondance avancée artiste/titre et contrôle de version ;
- protection contre les previews, karaokés, tributes, covers et versions alternatives indésirables ;
- validation FFprobe/FFmpeg avant stockage définitif ;
- worker continu pour les pochettes d’album ;
- interface FastAPI principale sur le port `8040` ;
- AI Control Room et fonctions Operator sur le port `8041` ;
- service local Log & AI Control sur le port `8042` ;
- intégration locale Ollama/Qwen pour le diagnostic et l’administration bornés ;
- mises à jour GitHub automatiques avec sauvegarde et rollback ;
- stockage musical externe via Samba.

## Services et ports

```text
8040  application principale Top40Archiver
8041  AI Control Room / Operator Chat
8042  service local Log & AI Control
11434 Ollama, local uniquement
```

Services principaux :

```bash
systemctl status top40-archiver-web.service --no-pager
systemctl status top40-archiver-ai.service --no-pager
systemctl status top40-download-manager.service --no-pager
systemctl status top40-log-reader.service --no-pager
systemctl status top40-archiver-cover-art.service --no-pager
systemctl status ollama.service --no-pager
```

Suivre le gestionnaire de téléchargement en direct :

```bash
journalctl -u top40-download-manager.service -f
```

## Stockage et bases de données

Base principale :

```text
/var/lib/top40-archiver/top40.sqlite3
```

Mémoire AI :

```text
/var/lib/top40-archiver/ai_memory.sqlite
```

Fichiers de téléchargement temporaires :

```text
/var/lib/top40-archiver/download-temp
```

Stockage musical par défaut :

```text
/mnt/top40-music/Top40
```

Exemple :

```text
/mnt/top40-music/Top40/Pop/A/Adele - Hello.mp3
```

## Nouvelle installation sur Debian 13

```bash
git clone https://github.com/Techraym/Top40Archiver.git
cd Top40Archiver
chmod +x install.sh update-existing.sh update-from-github.sh auto-update.sh setup-network-share.sh update-timer.sh
su -c ./install.sh
```

Puis ouvrir :

```text
http://<IP-DU-NUC>:8040
```

## Mettre à jour une installation existante

```bash
su -
curl -fL \
  https://raw.githubusercontent.com/Techraym/Top40Archiver/main/update-from-github.sh \
  -o /tmp/update-top40-archiver.sh
chmod +x /tmp/update-top40-archiver.sh
/tmp/update-top40-archiver.sh
```

La version 1.16.22 contient également :

```text
scripts/install-1.16.22.sh
```

La base existante, les paramètres, la progression historique et le stockage musical restent couverts par le contrat de mise à jour/rollback.

## Politique de téléchargement

Top40Archiver utilise un Multi Source Download Engine avec des chemins fournisseurs contrôlés. Les candidats sont évalués selon leur identité et les métadonnées disponibles, puis validés techniquement avant le stockage définitif.

Limites de sécurité importantes :

- les fichiers audio existants ne sont pas supprimés de façon autonome ;
- les fichiers audio existants ne sont pas écrasés silencieusement ;
- aucun contournement de CAPTCHA ;
- aucune automatisation de comptes personnels ou de cookies comme solution de contournement ;
- aucune rotation de proxy pour éviter des blocages ;
- aucun contournement de rate limit ;
- la correspondance des candidats et la validation audio restent obligatoires.

## AI Operations

La couche AI locale prend notamment en charge le diagnostic opérationnel, la surveillance des services, l’analyse des téléchargements, l’analyse des fournisseurs, la fraîcheur des classements, la surveillance des pochettes, Operator Chat et des actions de récupération limitées.

L’AI ne dispose pas d’un shell libre illimité. Les limites de sécurité strictes ne peuvent pas être assouplies de façon autonome. L’application principale sur le port `8040` doit rester disponible si la couche AI rencontre un problème.

## Mises à jour automatiques

Le programme de mise à jour compare le commit installé localement avec GitHub `main` et enregistre l’état des mises à jour sous :

```text
/var/lib/top40-archiver/update-state/
```

État :

```bash
systemctl status top40-archiver-auto-update.timer --no-pager
journalctl -u top40-archiver-auto-update.service -n 100 --no-pager
```

Forcer une vérification/réinstallation :

```bash
/opt/top40-archiver/auto-update.sh --force
```

## Samba

Vérifier d’abord le stockage externe :

```bash
findmnt /mnt/top40-music
runuser -u top40archiver -- test -w /mnt/top40-music && echo "Écriture possible"
```

Configurer :

```bash
/opt/top40-archiver/setup-network-share.sh
```

Chemin Windows :

```text
\\Top40\Top40Music
```

## Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
pytest
```

La version **1.16.22** a été validée avec **257 tests réussis** et un contrôle de syntaxe Python sans erreur.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Mises à jour et Samba](docs/UPDATE_AND_SMB.md)
- [Version 1.16.22](docs/RELEASE-1.16.22.md)
- [Changelog](CHANGELOG.md)
- [Contribution](CONTRIBUTING.md)
- [Sécurité](SECURITY.md)

## Utilisation légale

Utilisez la fonction de téléchargement uniquement pour les contenus pour lesquels vous disposez d’une autorisation ou d’une autre base juridique valable. L’utilisateur reste responsable du respect du droit d’auteur et des conditions des services utilisés.

## Licence

MIT — voir [LICENSE](LICENSE).
