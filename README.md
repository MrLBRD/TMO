# 🏉 TMO : Television Match Official

**Système de vidéo-vérification pour la préparation de commandes de rugby.**

Ce projet permet d'automatiser l'enregistrement vidéo de chaque colis via une webcam Logitech C270, déclenché par la lecture d'un QR code, avec une gestion intelligente du stockage et une interface de contrôle moderne.

-----

## 📋 Spécifications Techniques

  * **Langage :** Python 3.10+
  * **Plateforme cible :** Windows (Développement sur Mac possible)
  * **Matériel :** Webcam Logitech C270 (fixée au-dessus de la table)
  * **Trigger :** QR Code (10 caractères)
  * **Flux Web :** Communication via HTTP (Poll/Webhook)
  * **Rétention :** Auto-suppression des rushs après 45 jours.

-----

## 🛠️ Pile Logicielle (Libraries)

| Bibliothèque | Usage |
| :--- | :--- |
| `opencv-python` | Capture vidéo, enregistrement MP4 et traitement d'image. |
| `pyzbar` | Décodage ultra-rapide des QR Codes. |
| `customtkinter` | Interface graphique (GUI) moderne et responsive. |
| `requests` | Envoi des statuts au site web de gestion. |
| `pathlib` / `os` | Gestion des fichiers et rotation des 45 jours. |
| `threading` | Gestion du scan QR et de l'encodage sans figer l'interface. |

-----

## 📂 Structure du Projet

```text
TMO_PROJECT/
├── main.py              # Point d'entrée, interface CustomTkinter
├── core/
│   ├── recorder.py      # Logique de capture vidéo et scan QR
│   ├── network.py       # Fonctions d'envoi HTTP (API/Poll)
│   └── storage.py       # Gestion des fichiers et nettoyage (45j)
├── output/              # Dossier de stockage des vidéos (.mp4)
├── resources/           # Icônes ou sons (bip de scan)
├── requirements.txt     # Liste des dépendances
└── build_win.py         # Script pour générer l'exécutable Windows
```

-----

## ⚙️ Éléments à Développer

### 1\. Module de Vision (Recorder)

  * **Scan Sélectif :** Configurer `pyzbar` pour ignorer les EAN/Gencodes et ne lire que les QR codes de 10 caractères.
  * **Buffer Vidéo :** Maintenir un flux constant pour l'affichage tout en compressant le fichier en arrière-plan.
  * **Indicateur visuel :** Superposer un cercle rouge "REC" sur le flux vidéo quand l'enregistrement est actif.

### 2\. Interface Utilisateur (GUI)

  * **Fenêtre principale :** Vue en direct de la webcam.
  * **Barre d'état :** Affiche "Prêt", "Enregistrement en cours : [ID\_COMMANDE]" ou "Erreur Réseau".
  * **Bouton Manuel :** Un gros bouton "STOP" pour arrêter l'enregistrement si le scan automatique du colis suivant n'est pas utilisé.

### 3\. Logique de Stockage (Storage)

  * **Nommage :** `YYYY-MM-DD_ID-COMMANDE.mp4`.
  * **Fonction `clean_old_videos()` :** \* S'exécute à chaque démarrage.
      * Calcule $date\_actuelle - 45\_jours$.
      * Supprime récursivement les fichiers obsolètes.

### 4\. Communication Web (Network)

  * **HTTP Post :** Dès qu'un scan est validé, envoyer un JSON : `{"order_id": "ABC1234567", "timestamp": "...", "status": "video_started"}`.

-----

## 🚀 Workflow Opérationnel

1.  **Démarrage :** L'opérateur lance `TMO.exe`. Le système vérifie l'espace disque et nettoie les vieux fichiers.
2.  **Attente :** La caméra affiche le flux en direct. L'algorithme cherche un QR Code dans la zone centrale.
3.  **Scan :** L'opérateur passe le bon de commande sous la caméra.
      * *Action :* Bip sonore + Début de l'enregistrement + Envoi info au site web.
4.  **Préparation :** L'opérateur prépare les crampons/protections devant la caméra.
5.  **Clôture :** \* Soit l'opérateur scanne le QR code de la **commande suivante** (Arrêt du précédent + Start du nouveau).
      * Soit l'opérateur clique sur "STOP" (Fin de journée ou pause).

-----

## 📦 Déploiement (Mac vers Windows)

Pour transformer ce projet en exécutable Windows depuis votre environnement :

1.  **Environnement :** Utiliser un `venv` Python.
2.  **Compilation :** Utiliser `PyInstaller`.
    ```bash
    pyinstaller --noconsole --onefile --add-data "resources;resources" main.py
    ```
3.  **Note Windows :** Assurez-vous d'installer les "Visual C++ Redistributable" sur le PC cible pour que `pyzbar` (librairie C) fonctionne.

-----

## 🔄 Publier une nouvelle version (release)

### Étapes

1. **Mettre à jour le numéro de version** dans les 3 fichiers suivants :

   | Fichier | Variable |
   | :--- | :--- |
   | `main.py` | `__version__ = "X.Y.Z"` |
   | `installer.iss` | `#define MyAppVersion "X.Y.Z"` |
   | `chrome_extension/manifest.json` | `"version": "X.Y.Z"` |

2. **Commiter et pousser un tag** `vX.Y.Z` :
   ```bash
   git add main.py installer.iss chrome_extension/manifest.json
   git commit -m "chore: bump version to X.Y.Z"
   git tag vX.Y.Z
   git push origin main
   git push origin vX.Y.Z
   ```

3. **GitHub Actions** détecte le tag `v*` → lance le workflow `Build TMO Windows` :
   - Build PyInstaller (`TMO.spec`)
   - Build installateur Inno Setup (`installer.iss`) → `TMO_Setup.exe`
   - Crée automatiquement une release GitHub avec `TMO_Setup.exe` en asset

### Mécanisme de mise à jour in-app

L'application intègre un système de MAJ automatique (`core/updater.py`) :

1. Au clic sur **"Vérifier MAJ"** (fenêtre Configuration), l'app interroge l'API GitHub : `GET /repos/MrLBRD/TMO/releases/latest`
2. Si la version du tag distant est supérieure à `__version__`, le bouton de téléchargement apparaît
3. `TMO_Setup.exe` est téléchargé dans le dossier temp système
4. L'installateur est lancé en **processus détaché** — l'app se ferme, l'installateur tourne seul
5. Au prochain démarrage, l'app détecte qu'elle vient d'être mise à jour et affiche une notification

> **Note :** La release GitHub **doit** contenir un asset nommé exactement `TMO_Setup.exe`, c'est le nom attendu par `updater.py` (`INSTALLER_ASSET_NAME`).

-----

## 💡 Conseils pour la Logitech C270

  * **Lumière :** La C270 gère mal les faibles luminosités. Prévoyez un éclairage direct sur la table pour éviter le grain sur la vidéo (ce qui gêne la lecture du QR code).
  * **Focus :** Si le QR code est flou, il faudra peut-être ouvrir la webcam (vis sous l'autocollant) pour régler manuellement la bague de mise au point, car elle est réglée d'usine pour l'infini (visage).
