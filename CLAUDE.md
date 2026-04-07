# Project Overview

TMO est une application de bureau Python qui enregistre automatiquement des vidéos de préparation de commandes e-commerce. Un opérateur scanne un QR code sur un ticket (type ticket de caisse) avec une webcam ; l'app démarre un enregistrement MP4 horodaté et ouvre la page de commande dans Chrome. Une extension Chrome ferme automatiquement les anciens onglets pour garder l'interface nette.

# Architecture

```
main.py              — Orchestrateur principal : GUI CustomTkinter, event loop, threads
core/
  recorder.py        — Capture vidéo (OpenCV), détection QR (pyzbar), écriture MP4
  storage.py         — Gestion fichiers : chemins, nettoyage rétention, espace disque
  config.py          — Chargement/sauvegarde config JSON, surcharge par variables d'env
  logging_setup.py   — RotatingFileHandler (1 MB × 3 backups, tmo.log)
  updater.py         — Auto-update via GitHub Releases (télécharge TMO_Setup.exe, vérifie SHA256)
chrome_extension/
  background.js      — Service worker MV3 : suit les onglets TMO ouverts, ferme les anciens
  manifest.json      — Permissions : tabs, storage, alarms ; host : wp-admin/admin.php*
```

### Modèle de threads
- **Thread principal** : boucle UI tkinter
- **Thread capture** : lecture caméra à ~30fps, détection QR
- **Thread writer** : encodage MP4 en fond (découplé via queue)
- **Threads daemon** : ouverture navigateur (non bloquant)

### Flux principal
1. Scan QR code `Tk-{ORDER_ID}` → `_handle_order_id()`
2. Arrêt de l'enregistrement précédent (si actif)
3. Démarrage nouvel enregistrement
4. Ouverture Chrome sur `/wp-admin/admin.php?page=wc-better-management&orderCheck={order_id}`
5. Extension Chrome ferme les anciens onglets TMO
6. Prochain scan ou STOP manuel → enregistrement arrêté

# Tech Stack

- **Python 3.10+** (typage strict, dataclasses)
- **CustomTkinter** — GUI moderne dark mode
- **OpenCV (cv2)** — Capture webcam, encodage MP4, fallback QR
- **pyzbar** — Détection QR rapide (bibliothèque C) avec fallback OpenCV
- **Pillow (PIL)** — Conversion frames pour affichage tkinter
- **PyInstaller** — Compilation → EXE Windows
- **Inno Setup** — Installeur Windows (produit `TMO_Setup.exe`)
- **GitHub Actions** — CI/CD : build + release automatique sur tag `v*`
- **Chrome Extension MV3** — Service worker, `chrome.storage.local`, `chrome.alarms`

# Coding Conventions

- Type hints partout (Python 3.10+, `from __future__ import annotations` si besoin)
- Dataclass pour la config (`AppConfig`)
- Gestion d'erreurs : try/except sur toutes les opérations I/O ; les erreurs ne bloquent jamais l'enregistrement en cours
- Les opérations lentes (browser, encodage) sont systématiquement déportées dans des threads daemon
- Les events entre threads transitent par une `queue.Queue` lue dans `_poll_events()` toutes les 100ms
- Format de fichier vidéo : `output/YYYY/MM/DD/{ORDER_ID}.mp4`
- Format QR attendu : `Tk-{ORDER_ID}` (ORDER_ID : 5-10 caractères alphanumériques)
- Logging structuré via `logging` Python ; `api_key` et URLs sensibles ne sont jamais loggués

# Folder Structure

```
TMO/
├── main.py                  # Point d'entrée, classes TmoApp / ConfigWindow / OverlayWindow / DeadManSwitchDialog
├── core/                    # Modules métier (recorder, storage, config, logging_setup, updater)
├── chrome_extension/        # Extension Chrome (manifest.json + background.js)
├── .github/workflows/       # CI/CD GitHub Actions (build-windows.yml)
├── .github/dependabot.yml   # Mise à jour automatique des actions GitHub (hebdomadaire)
├── TMO.spec                 # Configuration PyInstaller
├── installer.iss            # Configuration Inno Setup (version FR+EN)
├── build_win.py             # Script de build Windows
├── requirements.txt         # Dépendances Python (versions épinglées avec ==)
└── output/                  # Vidéos enregistrées (YYYY/MM/DD/{ORDER_ID}.mp4) — gitignore
```

# Commands

```bash
# Développement local
pip install -r requirements.txt
python main.py

# Build Windows (depuis Windows ou GitHub Actions)
python build_win.py          # PyInstaller → dist/TMO.exe
# puis Inno Setup sur installer.iss → TMO_Setup.exe
```

# Versioning & Release

Les trois fichiers suivants doivent toujours être synchronisés sur la même version :
- `main.py` → `__version__ = "X.Y.Z"`
- `installer.iss` → `#define MyAppVersion "X.Y.Z"`
- `chrome_extension/manifest.json` → `"version": "X.Y.Z"`

```bash
git commit -m "chore: bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main && git push origin vX.Y.Z
# GitHub Actions crée automatiquement la release avec TMO_Setup.exe et TMO_Setup.exe.sha256
```

# Configuration

Fichier : `%APPDATA%\TMO\config.json` (Windows) / `~/.config/TMO/config.json` (Linux/Mac)

| Clé | Défaut | Description |
|-----|--------|-------------|
| `camera_index` | `0` | Index caméra OpenCV |
| `camera_flip` | `"none"` | `none` / `horizontal` / `vertical` / `both` |
| `output_dir` | `~/TMO/output/` | Dossier de sortie vidéos |
| `retention_days` | `45` | Rétention vidéos (jours) |
| `max_recording_minutes` | `15` | Dead man's switch (0 = désactivé) |
| `site_url` | `""` | URL du site WooCommerce (doit commencer par `https://` ou `http://`) |

Toutes les clés sont surchargeables par variables d'environnement `TMO_*`.

# Important Rules

- **Ne jamais bloquer le thread principal** : toute opération lente passe par un thread daemon ou une queue
- **L'enregistrement vidéo est prioritaire** : les erreurs navigateur ou stockage ne doivent jamais interrompre un enregistrement en cours
- **Sécurité fichiers** : `sanitize_order_id()` doit être appelée sur tout ORDER_ID avant usage dans un chemin de fichier
- **Synchronisation versions** : toujours bumper les 3 fichiers de version ensemble (main.py, installer.iss, manifest.json)
- **Dead man's switch** : si `max_recording_minutes > 0`, un dialogue de confirmation apparaît à l'expiration — l'enregistrement s'arrête automatiquement après 60s sans réponse
- **Espace disque** : alerte rouge < 2 Go, orange < 10 Go ; la rétention se nettoie au démarrage et à chaque sauvegarde de config
- **Extension Chrome** : installée en mode non-packagé (dossier `chrome_extension/`) — l'utilisateur doit la recharger manuellement après une mise à jour de l'app
- **Intégrité des mises à jour** : la CI publie `TMO_Setup.exe.sha256` ; `download_update()` vérifie le SHA256 avant de retourner le chemin de l'installateur
- **Dépendances épinglées** : toutes les dépendances Python dans `requirements.txt` sont épinglées avec `==` ; toutes les actions GitHub sont épinglées par SHA complet
- **QR scanner** : `_qr_available` n'est mis à `False` qu'après `_QR_ERROR_THRESHOLD` (10) exceptions consécutives — un succès remet le compteur à zéro
