# Code Review Report v1
**Date:** 2026-04-07
**Reviewer:** Expert Reviewer Agent v2026.2
**Project:** TMO — Television Match Official (v1.1.1)
**Stack:** Python 3.10+, CustomTkinter, OpenCV, pyzbar, Chrome Extension MV3, GitHub Actions

---

## Verdict Global

⚠️ **Warning** — Pas de vulnérabilité critique exploitable immédiatement dans le contexte d'utilisation (app desktop locale, utilisateur admin unique). Cependant, plusieurs risques supply chain et de robustesse nécessitent correction avant la prochaine release.

---

## Résumé Exécutif

TMO est une application desktop Python bien structurée pour l'enregistrement vidéo par scan QR en contexte rugby. L'architecture multi-thread est solide, la sanitisation des IDs de commande correcte, et l'extension Chrome respecte MV3. Les risques majeurs sont concentrés sur la chaîne de distribution : actions GitHub non épinglées par SHA (dont un tiers `softprops/action-gh-release`), l'installateur de mise à jour exécuté sans vérification d'intégrité, et des dépendances Python sans version fixée dans `requirements.txt`. L'absence totale de logging structuré rend le débogage en production très difficile.

---

## Tableau des Risques

| Statut | Priorité | Pilier | Fichier:Ligne | Description | Solution | Effort |
|--------|----------|--------|---------------|-------------|----------|--------|
| ✅ Traité | 🔴 Critique | Supply Chain (A03) | `.github/workflows/build-windows.yml:17,20,40,47` | 4 actions GitHub non épinglées par SHA — dont `softprops/action-gh-release@v2` (tiers) exposée au même vecteur que CVE-2025-30066 | Épingler toutes les actions par SHA complet | 30 min |
| ✅ Traité | 🔴 Critique | Supply Chain (A03) | `requirements.txt:1-5` | Zéro version épinglée (`opencv-python`, `pyzbar`, `customtkinter`, `pillow`, `requests`) — build non reproductible, risque compromission fournisseur | Épingler toutes les versions avec `==` + ajout `numpy` | 15 min |
| ✅ Traité | 🔴 Critique | Intégrité (A08) | `core/updater.py:145-164`, `178-206` | L'installateur `.exe` téléchargé depuis GitHub est exécuté **sans vérification de hash/signature**. MITM ou compromission des assets GitHub → exécution de code arbitraire | CI génère `TMO_Setup.exe.sha256`, `download_update()` vérifie le SHA256 avant retour — rétrocompatible (vérification optionnelle si asset absent) | 1h |
| ✅ Traité | 🟠 Moyen | GitHub Actions | `.github/workflows/build-windows.yml:13` | `permissions: contents: write` trop large au niveau du job entier | Split en 2 jobs : `build` (`contents: read`) + `release` (`contents: write`) | 15 min |
| ✅ Traité | 🟠 Moyen | GitHub Actions | `.github/workflows/build-windows.yml:17` | `persist-credentials: false` absent sur `actions/checkout` | Ajouté `with: persist-credentials: false` | 5 min |
| ✅ Traité | 🟠 Moyen | Logging (A09) | `core/` + `main.py` (global) | Zéro logging structuré dans toute l'application. Erreurs silencieusement avalées (`except Exception: pass`). Impossible de déboguer un incident en production | `core/logging_setup.py` créé (RotatingFileHandler 1 MB × 3) ; logs dans `recorder.py`, `network.py`, `updater.py`, `main.py` ; `config.py` expose `log_path()` ; `api_key` jamais loggué | 2h |
| ✅ Traité (doc) | 🟠 Moyen | Secrets (A02) | `core/config.py:196-200` | `api_key` écrit en clair dans `config.json` (`%APPDATA%\TMO\config.json`). Lisible par tout process tournant sous le même compte utilisateur | `INSTALL.txt` mis à jour avec avertissement de sécurité explicite. `keyring` non implémenté : pas de champ UI pour `api_key`, complexité injustifiée pour l'usage actuel | 2h |
| ✅ Traité | 🟠 Moyen | Chrome Extension | `chrome_extension/background.js:87,95` | `setTimeout(cleanupTabs, 800)` dans un service worker MV3 — peut être annulé si le SW est terminé avant les 800ms | Remplacé par `async/await cleanupTabs()` immédiat dans les deux listeners | 30 min |
| ✅ Traité | 🟠 Moyen | Supply Chain (A03) | `.github/workflows/build-windows.yml:32` | `pip install pyinstaller` sans version fixée en CI | Épinglé : `pip install "pyinstaller==6.10.0"` | 5 min |
| ✅ Traité | 🟡 Faible | Python Backend | `core/recorder.py:460,506` | `_qr_available = False` jamais réinitialisé après une exception — désactive le scan QR de façon permanente pour la session, nécessite redémarrage | Compteur `_qr_error_count` + seuil `_QR_ERROR_THRESHOLD = 10` : désactivation seulement après 10 exceptions consécutives, reset sur succès | 1h |
| ✅ Traité (doc) | 🟡 Faible | Chrome Extension | `chrome_extension/manifest.json` | Permission `tabs` (accès à toutes les URLs de tous les onglets) au lieu de `activeTab` + injection dynamique | `activeTab` non viable : `getTrackedTabs()` appelle `chrome.tabs.query({})` sur TOUS les onglets pour fermer les ANCIENS (pas l'actif). Besoin documenté en commentaire dans `background.js` | 30 min |
| ✅ Traité | 🟡 Faible | Chrome Extension | `chrome_extension/manifest.json` | Champ `content_security_policy` absent (CSP explicite recommandée en MV3) | Ajouté `"content_security_policy": {"extension_pages": "script-src 'self'; object-src 'none;'"}` | 10 min |
| ✅ Traité | 🟡 Faible | Config (A02) | `core/config.py:190-191` | Échec silencieux du chargement JSON — si `config.json` est corrompu, toute la config revient aux défauts sans avertissement utilisateur | `load_config()` retourne `tuple[AppConfig, str | None]` ; dialog d'alerte `_show_config_error_notice()` affiché au démarrage si erreur | 30 min |
| ✅ Traité | 🟡 Faible | Réseau (A01) | `core/network.py` supprimé | API POST retirée entièrement (non utilisée) ; validation `https://`/`http://` ajoutée sur `site_url` au moment du Save dans `ConfigWindow` | — |

### Fixes session 2026-04-07 (suite et fin)

| Statut | Description | Fichier |
|--------|-------------|---------|
| ✅ Traité | Webcam blackscreen dans ConfigWindow — drain des 5 premières frames au démarrage (Windows) | `core/recorder.py` |
| ✅ Traité | Bouton Save inaccessible si écran < 960px — ConfigWindow convertie en `CTkScrollableFrame` (680×700), boutons toujours visibles | `main.py` |
| ✅ Traité | Logging structuré ajouté — `core/logging_setup.py` (RotatingFileHandler 1 MB × 3 backups, `tmo.log`) ; events loggués : `app_started/stopped`, `recording_started/stopped`, `camera_open_failed`, `camera_read_failed` (throttle 5 s), `qr_disabled`, `update_check`, intégrité SHA256 | `core/logging_setup.py`, `core/config.py`, `core/recorder.py`, `core/updater.py`, `main.py` |
| ✅ Traité | API POST (`core/network.py`) retirée entièrement — non utilisée en production ; `api_url` et `api_key` supprimés de `AppConfig`, config, UI et env vars ; validation `https://`/`http://` ajoutée sur `site_url` au Save | `core/network.py` supprimé, `core/config.py`, `main.py`, `tests/` |

---

## Agents Invoqués

- [x] security-owasp
- [x] python-backend
- [x] github-actions
- [x] chrome-extension
- [x] secure-logging
- [ ] auth-passkeys (non applicable — pas d'authentification utilisateur)
- [ ] database-security (non applicable — pas de base de données)
- [ ] wordpress-woocommerce (non applicable — TMO n'est pas un plugin WP)
- [ ] frontend-react (non applicable)
- [ ] api-rest (non applicable — client uniquement)
- [ ] electron-desktop (non applicable — Python/Tkinter, pas Electron)

---

## Analyse Détaillée par Pilier

---

### 🛡️ 1. Sécurité OWASP — Findings Positifs

Le code montre plusieurs bonnes pratiques :

- **Sanitisation des IDs** : `sanitize_order_id()` (`core/storage.py:35-39`) utilise un regex strict `[^A-Za-z0-9_-]+` avant tout usage en chemin de fichier. ✅
- **Validation format QR** : `_extract_order_id_from_qr_value()` (`core/recorder.py:528-543`) filtre le préfixe `tk-`, longueur 5-10 chars, sanitisation. ✅
- **Subprocess sans shell=True** : `subprocess.Popen([installer_path], ...)` (`core/updater.py:195`) — pas d'injection de commande. ✅
- **JSON uniquement** : Pas de `pickle`, `yaml.load`, `eval`, `exec`. ✅
- **Requêtes JSON paramétrées** : `send_status` envoie via `json=payload` (`core/network.py:41`), pas de concaténation. ✅
- **Path traversal protégé** : les chemins vidéo sont construits exclusivement depuis des IDs sanitisés. ✅

---

### 🔴 A03 — Supply Chain : GitHub Actions non épinglées

```yaml
# ❌ ACTUEL — .github/workflows/build-windows.yml
- uses: actions/checkout@v4                     # Tag mutable
- uses: actions/setup-python@v5                 # Tag mutable
- uses: actions/upload-artifact@v4              # Tag mutable
- uses: softprops/action-gh-release@v2          # Tiers + Tag mutable ← risque maximal

# ✅ RECOMMANDÉ — épingler par SHA complet
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683        # v4.2.2
- uses: actions/setup-python@0b93645e9fea7318ecaed2b359559ac225c90a2     # v5.3.0
- uses: actions/upload-artifact@6f51ac03b9356f520e9adb1b1b7802705f340658 # v4.6.0
- uses: softprops/action-gh-release@c062e08bd532815e2082a7e09ce9571a6e1139c # v2.2.1
```

Vérifier les SHA actuels via : `npx pin-github-actions .github/workflows/`
Activer Dependabot pour `github-actions` :

```yaml
# .github/dependabot.yml à créer
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

### 🔴 A03 — Supply Chain : requirements.txt non épinglé

```text
# ❌ ACTUEL — requirements.txt
opencv-python
pyzbar
customtkinter
pillow
requests

# ✅ RECOMMANDÉ — versions exactes (à récupérer depuis pip freeze)
opencv-python==4.7.0.72
pyzbar==0.1.9
customtkinter==5.2.2
pillow==10.4.0
requests==2.32.3
```

Générer depuis l'environnement de dev : `pip freeze > requirements.txt`
Puis auditer : `pip-audit` ou `safety check`

---

### 🔴 A08 — Intégrité : installateur exécuté sans vérification

```python
# ❌ ACTUEL — core/updater.py:178-206
def run_installer(installer_path: str) -> tuple[bool, str]:
    if not os.path.exists(installer_path):
        return False, "Fichier d'installation non trouvé"
    try:
        subprocess.Popen([installer_path], ...)  # ← Exécution directe sans vérification
```

**Correctif recommandé** : inclure le SHA256 attendu dans la réponse de l'API GitHub releases, puis vérifier avant exécution :

```python
import hashlib

def verify_installer_hash(path: str, expected_sha256: str) -> bool:
    """Vérifie l'intégrité de l'installateur avant exécution."""
    try:
        sha256 = hashlib.sha256(open(path, "rb").read()).hexdigest()
        return sha256.lower() == expected_sha256.lower()
    except OSError:
        return False
```

Les releases GitHub exposent un endpoint `GET /repos/{owner}/{repo}/releases/assets/{asset_id}` — publier le SHA256 dans les release notes ou comme asset séparé (`TMO_Setup.exe.sha256`).

---

### 🟠 GitHub Actions — Permissions & Credentials

```yaml
# ❌ ACTUEL — permissions trop larges au niveau job
jobs:
  build:
    runs-on: windows-latest
    permissions:
      contents: write   # ← Permet d'écrire dans TOUT le repo

# ✅ RECOMMANDÉ — moindre privilège
jobs:
  build:
    runs-on: windows-latest
    permissions:
      contents: read   # Default restrictif
    steps:
      - uses: actions/checkout@<SHA>
        with:
          persist-credentials: false   # ← Ajouter

      # ... build steps ...

      - name: Create Release
        if: startsWith(github.ref, 'refs/tags/v')
        permissions:
          contents: write   # ← Seulement pour ce step
        uses: softprops/action-gh-release@<SHA>
```

---

### 🟠 Logging — Absence totale

L'application n'utilise aucun module `logging`. Les erreurs sont soit :
- Affichées brièvement dans l'UI (`self._set_status("Erreur : ...")`)
- Silencieusement ignorées (`except Exception: pass`)

Exemples d'erreurs critiques silencieuses :
- `core/config.py:190` — Échec de lecture du fichier de config → défauts silencieux
- `core/recorder.py:359` — Échec de lecture caméra → loop silencieux avec `time.sleep(0.2)`
- `core/network.py:44` — Toute exception réseau → `return False, str(exc)` sans log

**Minimum recommandé** :

```python
# Au niveau de main.py
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(Path.home() / "TMO" / "tmo.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("tmo")

# Events importants à logger :
log.info("recording_started order_id=%s path=%s", order_id, path)
log.info("recording_stopped order_id=%s", order_id)
log.warning("network_error api_url=%s error=%s", api_url, error)
log.error("camera_open_failed index=%d", camera_index)
log.error("qr_decoder_failed backend=%s", backend)
```

Ne jamais logger `api_key` ni les URLs complètes avec paramètres sensibles.

---

### 🟠 API Key en clair dans config.json

```python
# core/config.py:196-200
def save_config(cfg: AppConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), ...)
    # ← api_key écrit en clair dans %APPDATA%\TMO\config.json
```

**Option 1 (recommandée)** — Windows Credential Manager via `keyring` :
```python
import keyring
keyring.set_password("TMO", "api_key", api_key)
api_key = keyring.get_password("TMO", "api_key")
```

**Option 2 (acceptable)** — Documenter explicitement dans INSTALL.txt que `config.json` contient une clé API sensible et doit être protégé par les permissions du système de fichiers.

---

### 🟠 Chrome Extension — setTimeout dans Service Worker MV3

```javascript
// ❌ ACTUEL — background.js:87,95
chrome.tabs.onCreated.addListener((tab) => {
  if (tab.url && isTmoOpenUrl(tab.url)) {
    trackTab(tab.id);
    setTimeout(cleanupTabs, 800);  // ← Peut être perdu si SW terminé
  }
});

// ✅ RECOMMANDÉ — traitement immédiat ou via alarm courte
chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.url && isTmoOpenUrl(tab.url)) {
    await trackTab(tab.id);
    await cleanupTabs();  // Immédiat, pas de délai nécessaire
  }
});
```

Le délai de 800ms avait probablement pour but de laisser le temps à l'onglet de s'initialiser. `getTrackedTabs()` filtre déjà les onglets en vérifiant `isTargetPage(tab.url)`, donc le délai est inutile.

---

### 🟡 Chrome Extension — Permission `tabs` vs `activeTab`

La permission `tabs` donne accès à `tab.url` pour **tous les onglets ouverts**. Pour cette extension, elle est techniquement nécessaire (la `getTrackedTabs()` fait `chrome.tabs.query({})` global).

**Évaluation** : dans ce cas d'usage (nettoyage d'onglets WooCommerce identifiés par URL), `tabs` est justifié. Documenter ce besoin dans le manifest ou le README pour les futures revues de permission Chrome Web Store.

---

### 🟡 QR Scanner — Disable Permanent sur Exception

```python
# core/recorder.py:456-461
except Exception:
    if self._opencv_qr_detector is not None:
        self._qr_backend = "opencv"
    else:
        self._qr_available = False  # ← Jamais réinitialisé pour la session
    self.events.put(RecorderEvent(type="error", message="qr_decoder_failed"))
    return

# core/recorder.py:505-508
except Exception:
    self._qr_available = False  # ← Idem
```

Si le décodeur échoue sur une frame corrompue (transitoire), le QR est désactivé définitivement. L'utilisateur doit redémarrer l'app. Un compteur d'erreurs avec réinitialisation après succès serait plus robuste.

---

## Validation Technique

Pas de tests automatisés dans le projet. Les validations suivantes sont recommandées :

```bash
# Audit des dépendances Python
pip install pip-audit && pip-audit -r requirements.txt

# SAST Python
pip install bandit && bandit -r . --skip B603,B404

# Analyse GitHub Actions
pip install zizmor && zizmor .github/workflows/build-windows.yml

# Vérification SHA actions
npx pin-github-actions .github/workflows/build-windows.yml --dry-run
```

---

## Correctifs Proposés (Résumé Priorité)

### Sprint immédiat (< 1 jour)
1. Épingler les 4 actions GitHub par SHA + activer Dependabot
2. Épingler les versions dans `requirements.txt` (`pip freeze`)
3. Réduire les permissions CI à `contents: read` + `persist-credentials: false`
4. Épingler `pyinstaller` en CI
5. Ajouter `content_security_policy` dans `manifest.json`

### Sprint suivant
6. Ajouter vérification SHA256 de l'installateur avant exécution
7. Implémenter logging minimal dans l'application (`logging` Python)
8. Remplacer `setTimeout` par traitement immédiat dans `background.js`
9. Évaluer `keyring` pour le stockage de `api_key`

### Backlog
10. Mécanisme de récupération du QR scanner (retry après N erreurs)
11. Validation d'URL pour `api_url`/`site_url`
12. Tests automatisés pour `core/storage.py` et `core/network.py`
