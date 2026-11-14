# TMO : Television Match Official

**Système d'enregistrement vidéo automatique pour la préparation de commandes e-commerce (rugby).**

Un opérateur scanne le QR code d'un ticket de commande avec une webcam. L'app démarre un enregistrement MP4 horodaté et ouvre la page de commande dans Chrome. Une extension Chrome ferme automatiquement les anciens onglets.

---

## Spécifications Techniques

- **Langage :** Python 3.12+
- **Plateforme cible :** Windows (développement sur Mac possible)
- **Matériel :** Webcam Logitech C270 (fixée au-dessus de la table)
- **Trigger :** QR Code format `Tk-{ORDER_ID}` (5-10 caractères alphanumériques)
- **Rétention :** Auto-suppression des vidéos après 45 jours (configurable)

---

## Pile Logicielle

| Bibliothèque | Usage |
| :--- | :--- |
| `opencv-python` | Capture webcam, encodage MP4, détection QR (fallback) |
| `pyzbar` | Décodage QR rapide (bibliothèque C) |
| `customtkinter` | Interface graphique moderne dark mode |
| `pillow` | Conversion frames pour affichage tkinter |
| `threading` | Capture, encodage et UI découplés |

---

## Structure du Projet

```text
TMO/
├── main.py                  # Point d'entrée — GUI, event loop, threads
├── core/
│   ├── recorder.py          # Capture vidéo (OpenCV), détection QR (pyzbar), écriture MP4
│   ├── storage.py           # Chemins, nettoyage rétention, espace disque
│   ├── config.py            # Chargement/sauvegarde config JSON
│   ├── logging_setup.py     # RotatingFileHandler (1 MB × 3 backups)
│   └── updater.py           # Auto-update via GitHub Releases + vérification SHA256
├── chrome_extension/
│   ├── background.js        # Service worker MV3 — ferme les anciens onglets TMO
│   └── manifest.json        # Permissions tabs, storage, alarms
├── .github/
│   ├── workflows/
│   │   └── build-windows.yml  # CI/CD : build PyInstaller + release GitHub
│   └── dependabot.yml         # Mise à jour automatique des actions GitHub
├── TMO.spec                 # Configuration PyInstaller
├── installer.iss            # Configuration Inno Setup
├── build_win.py             # Script de build Windows
├── requirements.txt         # Dépendances Python (versions épinglées)
└── output/                  # Vidéos enregistrées (gitignore)
```

---

## Workflow Opérationnel

1. **Démarrage :** L'opérateur lance `TMO.exe`. L'app vérifie l'espace disque et nettoie les vieux fichiers.
2. **Attente :** La caméra affiche le flux en direct. Le scanner cherche un QR code dans la zone centrale.
3. **Scan :** L'opérateur passe le bon de commande sous la caméra.
   - Bip sonore + début de l'enregistrement + ouverture Chrome sur la page de commande.
4. **Préparation :** L'opérateur prépare la commande devant la caméra.
5. **Clôture :**
   - Scan du QR code suivant → arrêt auto + démarrage du nouvel enregistrement.
   - Ou clic STOP (fin de journée / pause).

---

## Configuration

Fichier : `%APPDATA%\TMO\config.json` (Windows) / `~/.config/TMO/config.json` (Linux/Mac)

| Clé | Défaut | Description |
| :--- | :--- | :--- |
| `camera_index` | `0` | Index caméra OpenCV |
| `camera_flip` | `"none"` | `none` / `horizontal` / `vertical` / `both` |
| `output_dir` | `~/TMO/output/` | Dossier de sortie vidéos |
| `retention_days` | `45` | Rétention vidéos (jours) |
| `max_recording_minutes` | `15` | Dead man's switch (0 = désactivé) |
| `site_url` | `""` | URL WooCommerce (doit commencer par `https://`) |
| `scan_roi_percent` | `90` | Zone de scan QR (% de la frame, centré) |
| `qr_brightness` | `0` | Ajustement luminosité pour détection QR (-100 à +100) |
| `qr_contrast` | `1.0` | Ajustement contraste pour détection QR (0.5 à 3.0) |

Toutes les clés sont surchargeables par variables d'environnement `TMO_*`.

---

## Développement local

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## Publier une nouvelle version (release)

Trois fichiers doivent toujours être synchronisés :

| Fichier | Variable |
| :--- | :--- |
| `main.py` | `__version__ = "X.Y.Z"` |
| `installer.iss` | `#define MyAppVersion "X.Y.Z"` |
| `chrome_extension/manifest.json` | `"version": "X.Y.Z"` |

```bash
git commit -m "chore: bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main && git push origin vX.Y.Z
```

GitHub Actions détecte le tag `v*` → build PyInstaller + Inno Setup → release GitHub avec `TMO_Setup.exe`, `TMO_Setup.exe.sha256` et `TMO_Setup.exe.sha256.sig`.

### Mise à jour automatique

1. Au lancement (après 5 s) puis toutes les 24 h, l'app interroge l'API GitHub Releases (EXE installé seulement, pas `python main.py`)
2. Si version distante > `__version__` : téléchargement en arrière-plan, **signature ed25519 du `.sha256` puis SHA256 vérifiés** ; hôtes GitHub seulement, redirections comprises, 512 Mo au plus
3. Bas de la fenêtre : « Mise à jour vX prête : installée à la fermeture » + bouton **Installer**
4. **Installer** (refusé pendant un enregistrement) ou fermeture de l'app : enregistrement arrêté, hash revérifié, installateur lancé (`/SILENT` à la fermeture) ; UAC demandé
5. Échec réseau ou signature : rien d'installé, message court en bas de la fenêtre
6. Au prochain démarrage, notification "mise à jour effectuée"

> La release GitHub **doit** contenir `TMO_Setup.exe`, `TMO_Setup.exe.sha256` et `TMO_Setup.exe.sha256.sig`.

---

## Conseils pour la Logitech C270

- **Lumière :** La C270 gère mal les faibles luminosités. Prévoyez un éclairage direct sur la table.
- **Focus :** Si le QR code est flou, réglez manuellement la bague de mise au point (vis sous l'autocollant) — réglée d'usine pour l'infini.
- **Calibration QR :** Dans Configuration, l'aperçu est affiché en niveaux de gris (image exacte analysée par le scanner). Utilisez le bouton **Calibrer** pour trouver automatiquement les meilleurs réglages brightness/contrast en pointant la caméra sur un QR code immobile.
