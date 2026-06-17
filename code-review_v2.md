# Code Review Report v2
**Date:** 2026-06-17
**Reviewer:** Expert Reviewer Agent v2026.2
**Project:** TMO — enregistrement vidéo par scan QR (v1.2.2)
**Stack:** Python 3.10+, CustomTkinter, OpenCV, pyzbar, Chrome Extension MV3, GitHub Actions

---

## Verdict Global

✅ **Approuvé avec réserves** — Aucune vulnérabilité critique exploitable dans le contexte d'usage (app desktop locale, opérateur unique, surface réseau limitée à GitHub en HTTPS). Tous les points de la revue v1 sont **effectivement corrigés** (vérifié dans le code). Les axes restants sont surtout : **performance du chemin critique QR→Chrome** (priorité métier), un **bug latent** (`urljoin` non importé), et l'**hygiène supply-chain des dépendances transitives**.

---

## Résumé Exécutif

Le code a nettement mûri depuis v1 : sanitisation des IDs robuste, logging structuré en place, vérification SHA256 des mises à jour, actions CI épinglées par SHA, permissions au moindre privilège, CSP de l'extension, suite de tests (83 tests, **100% passants**). L'architecture multi-thread (capture / writer / UI) est saine et l'enregistrement est correctement priorisé sur les erreurs annexes.

Trois leviers ressortent. **(1) Performance** : la priorité « détecter très vite le QR » est freinée par le fait que **tout le rendu d'overlay (ROI + indicateur REC) s'exécute sur le thread de capture, juste avant le décodage QR** — et la caméra est ouverte sans réglage de résolution / FourCC MJPG / taille de buffer, ce qui ajoute de la latence sur Windows. **(2) Bug latent** : `urljoin` n'est jamais importé dans `main.py` ; l'appel lève systématiquement un `NameError` avalé par un `except Exception`, et seul le fallback fonctionne. **(3) Supply chain** : les dépendances **directes** sont épinglées, mais les **transitives** (`idna`, `urllib3`, `certifi`…) flottent et `pip-audit` remonte des CVE embarquées dans l'EXE ; 3 PRs Dependabot sont ouvertes et non mergées.

---

## Tableau des Risques

| Priorité | Pilier | Fichier:Ligne | Description | Solution | Effort |
|----------|--------|---------------|-------------|----------|--------|
| 🟠 Moyen | ⚡ Performance | `core/recorder.py:398-413` | Le rendu d'overlay (`frame.copy()` + 2× `addWeighted` plein cadre via `_draw_scan_roi`/`_draw_rec_indicator`) tourne **sur le thread de capture, avant le scan QR** → allonge la latence read→décodage | Déporter le dessin des overlays vers le thread d'affichage (`_update_frame`), sur l'image déjà réduite 960×540 | 1-2 h |
| 🟠 Moyen | ⚡ Performance | `core/recorder.py:236-265` | Caméra ouverte sans `CAP_PROP_FOURCC=MJPG`, sans résolution explicite, sans `CAP_PROP_BUFFERSIZE=1` → sur DSHOW/Windows, FPS bridé (YUY2) + latence de buffer entre le geste physique et la frame décodée | Fixer MJPG + résolution adaptée (C270 : 1280×720) + buffersize=1 ; tester sur le matériel cible | 1 h |
| 🟠 Moyen | 🧹 Qualité / A10 | `main.py:1415` | `urljoin` **non importé** → `NameError` systématique avalé par `except Exception`, seul le fallback s'exécute (control-flow par exception, code « voulu » mort) | `from urllib.parse import urljoin` **ou** supprimer le `try` et garder le fallback | 5 min |
| 🟠 Moyen | 🔗 Supply Chain (A03) | `requirements.txt`, `TMO.spec:15-26` | Dépendances **transitives non épinglées** (`idna`, `urllib3`, `certifi`, `charset_normalizer`) embarquées dans l'EXE ; `pip-audit` : `idna<3.15`, `urllib3<2.7.0` vulnérables | Lockfile complet (`pip-compile` → `requirements.lock`) + `pip-audit` en CI | 1-2 h |
| 🟠 Moyen | 🔗 Supply Chain (A03) | GitHub (process) | 3 PRs Dependabot ouvertes non mergées (#5 actions, #6 `requests`→2.34.2, #7 `numpy`→2.4.6) ; `pip-audit` en CI absent | Merger après validation build ; ajouter `pip-audit` comme gate CI | 30 min |
| 🟡 Faible | 🧹 Qualité | `build_win.py` vs `TMO.spec` | Deux chemins de build divergents : `build_win.py` (`--onefile` nu, icône inexistante) n'inclut **pas** les correctifs numpy/cv2 du `.spec` → EXE cassé si lancé localement | Faire de `build_win.py` un simple wrapper `pyinstaller TMO.spec`, ou le supprimer | 15 min |
| 🟡 Faible | 🛡️ A02 / Intégrité | `TMO.spec:57,64` | `upx=True` (faux positifs antivirus + léger délai de décompression au démarrage) ; EXE non signé (`codesign_identity=None`) → avertissements SmartScreen | `upx=False` ; envisager une signature Authenticode | 10 min / + |
| 🟡 Faible | ⚡ Perf / UX | `main.py:1378-1386` | `_apply_config` recrée le `Recorder` et **rouvre la caméra à chaque sauvegarde** de config, même quand seuls rétention/site_url changent (écran noir 0.5-2 s) | Ne redémarrer la caméra que si `camera_index`/`camera_flip` ont changé | 30 min |
| 🟡 Faible | 🗂️ Hygiène repo | GitHub | Repo **public sans licence** (`licenseInfo: null`) ; release **draft v1.2.2** résiduelle en doublon de la « Latest » | Confirmer public voulu / ajouter LICENSE ; supprimer le draft | 15 min |
| 🟡 Faible | 🔐 Intégrité (A08) | `core/updater.py:148-207` | `download_url`/`sha256_url` issus de l'API GitHub utilisés sans vérifier le host (`https://...github...`) ; SHA256 et binaire proviennent de la même source (pas de signature indépendante) | Allowlist d'host sur les URLs ; à terme, signature du binaire | 20 min / + |
| 🟡 Faible | ⚡ Performance | `main.py:1422-1424` | `webbrowser.register('chrome', …)` ré-enregistré à **chaque** ouverture d'onglet | `subprocess.Popen([chrome_path, url])` direct, ou register une seule fois | 15 min |

> Aucun item 🔴 Critique. Tous les 🔴/🟠 de la revue v1 sont confirmés **corrigés** dans le code actuel (voir § Suivi v1).

### ✅ Correctifs 🟠 Moyen appliqués (2026-06-17)

| Item | Fichier | Détail |
|------|---------|--------|
| Overlays hors du thread de capture | `recorder.py`, `main.py` | Dessin ROI/REC déplacé vers `decorate_display_frame()` appelé dans `_update_frame` (UI), sur l'image 960×540 |
| Réglages caméra basse latence | `recorder.py:start()` | `FOURCC=MJPG` + résolution 1280×720 (params constructeur) + `BUFFERSIZE=1`, en best-effort try/except |
| `urljoin` non importé | `main.py` | Suppression du `try`/`urljoin` mort, construction directe par f-string (order_id sanitisé) |
| Transitifs épinglés + `requests` | `requirements.txt` | `requests==2.34.2` + `certifi/charset-normalizer/idna/urllib3` épinglés aux versions corrigées |
| `pip-audit` en CI | `build-windows.yml` | Étape d'audit (`continue-on-error: true`) sur `requirements.txt` dans le job `test` |

Tests : **83/83 passants** après modifications.

### ✅ Correctifs 🟡 Faible appliqués (2026-06-17)

| Item | Fichier | Détail |
|------|---------|--------|
| Dérive `build_win.py` ↔ `.spec` | `build_win.py` | Réduit à un wrapper `pyinstaller TMO.spec --noconfirm` (source de vérité unique) |
| UPX (faux positifs AV) | `TMO.spec` | `upx=False` |
| Caméra rouverte à chaque save | `recorder.py`, `main.py` | `Recorder.apply_settings()` : mise à jour à chaud ROI/luminosité/contraste/sortie ; `Recorder` recréé **uniquement** si index/flip caméra change |
| `webbrowser.register` répété | `main.py` | `subprocess.Popen([chrome_path, url])` direct (plus de ré-enregistrement par ouverture) |
| URLs updater non validées | `updater.py` | Allowlist d'host HTTPS (`github.com`, `*.githubusercontent.com`) sur `download_url` et `sha256_url` |
| `host_permissions` redondant | `manifest.json` | Retiré (la permission `tabs` suffit) → **recharger l'extension** après mise à jour |
| Release draft v1.2.2 résiduelle | GitHub | Draft (id 308211428) supprimé ; tag `v1.2.2` et release publiée conservés |

> **Licence / repo public** : laissé tel quel — confirmé volontaire (projet libre).

Items restants (backlog, non bloquants) : signature Authenticode de l'EXE ; lockfile complet (`pip-compile`) en complément du pin transitif ; rendre `pip-audit` bloquant une fois le bruit maîtrisé.

---

## Agents Invoqués

- [x] security-owasp (base obligatoire)
- [x] python-backend
- [x] github-actions
- [x] chrome-extension
- [x] secure-logging
- [ ] database-security (non applicable — aucune persistance SQL/NoSQL)
- [ ] auth-passkeys (non applicable — pas d'authentification utilisateur)
- [ ] wordpress-woocommerce (non applicable — TMO est un client desktop)
- [ ] api-rest / frontend-react / electron-desktop (non applicables)

---

## Analyse Détaillée par Pilier

### ⚡ 1. Performance — Chemin critique QR → Chrome (priorité métier)

Le flux chaud est : `cap.read()` → flip → **dessin overlays** → stockage frame → enqueue writer → **scan QR**. Deux frictions ralentissent la détection.

**1.1 — Le rendu d'overlay s'exécute sur le thread de capture, avant le scan** (`recorder.py:398-413`)

```python
display_frame = frame.copy()                       # copie plein cadre
display_frame = self._draw_scan_roi(display_frame) # copy() + addWeighted plein cadre
if self.is_recording:
    display_frame = self._draw_rec_indicator(...)  # copy() + addWeighted plein cadre
with self._latest_frame_lock:
    self._latest_frame = display_frame
    self._latest_raw_frame = frame
self._enqueue_recording_frame(frame)
self._qr_frame_counter += 1
if self._qr_frame_counter >= self._qr_scan_interval:
    self._scan_and_handle(frame)                   # ← le scan attend que tout le dessin soit fini
```

À 720p, `_draw_scan_roi` + `_draw_rec_indicator` font 3 à 5 opérations plein cadre (`copy` + `addWeighted`, ~2,7 M pixels chacune) **à chaque frame**, juste avant le décodage. Or l'affichage n'a besoin que de ~30 fps et n'est pas le chemin prioritaire. 

**Recommandation** : ne stocker que la frame brute dans le thread de capture, et dessiner les overlays dans `_update_frame` (thread UI) sur l'image **déjà réduite à 960×540** (4× moins de pixels, et hors du chemin de scan). Le thread de capture se réduit alors à : `read → flip → store raw → enqueue → scan`, ce qui raccourcit directement la latence geste→détection. C'est le **levier n°1** pour « détecter très vite ».

**1.2 — Caméra ouverte sans réglages de latence/débit** (`recorder.py:236-265`)

Aucun `cap.set(...)` n'est appelé après ouverture. Conséquences sur Windows/DSHOW :
- format par défaut souvent **YUY2 (RAW)** → FPS bridé en HD ;
- **buffer interne** non limité → la frame lue peut être « en retard » de plusieurs trames sur le geste réel.

```python
# Après cap.isOpened(), avant la boucle :
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # débloque le 30 fps HD
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)                         # C270 : 1280x720
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)                             # ← réduit la latence (frame la + fraîche)
```

`BUFFERSIZE=1` est le réglage le plus impactant pour la **latence perçue** de détection. MJPG améliore le **débit**. À valider sur la C270 cible (certains drivers ignorent `BUFFERSIZE` — sans régression dans ce cas).

**1.3 — Ouverture Chrome** (`main.py:1409-1430`) ✅ déjà non bloquante (thread daemon) et chemin Chrome **mis en cache** (`_get_chrome_path`). Très bien. Reste mineur : `webbrowser.register` est rappelé à chaque ouverture — un `subprocess.Popen([chrome_path, url])` direct serait plus déterministe (low priority).

**1.4 — Frame skipping** (`recorder.py:182-183`) : scan 1 frame sur 2 (`_qr_scan_interval = 2`). Bon compromis ; une fois 1.1 appliqué, on pourrait repasser à chaque frame sans saturer le thread.

---

### 🧹 2. Qualité / A10 — `urljoin` non importé (bug latent)

`main.py:1415` :

```python
try:
    url = urljoin(base if base.endswith("/") else base + "/", f"wp-admin/admin.php?...")
except Exception:
    url = f"{base.rstrip('/')}/wp-admin/admin.php?page=wc-better-management&orderCheck={order_id}"
```

`urljoin` n'est **jamais importé** dans `main.py` (vérifié : aucun `from urllib.parse import urljoin`). L'appel lève donc un `NameError` à chaque exécution, capté par le `except Exception`, et **seul le fallback fonctionne**. Le résultat reste correct, mais :
- le code « voulu » (`urljoin`) est **mort** ;
- on s'appuie sur une exception pour le control-flow normal — piège classique (A10) : si quelqu'un resserre le `except`, l'app casse.

**Fix** : ajouter `from urllib.parse import urljoin`, **ou** supprimer le `try/except` et garder directement la construction par f-string (suffisante puisque `order_id` est sanitisé `[A-Za-z0-9_-]`).

---

### 🛡️ 3. Sécurité OWASP — Constats positifs et résiduels

**Confirmés bons :**
- **A05 Injection** : aucun `shell=True`, `os.system`, `eval`, `pickle`, `yaml.load`. `subprocess.Popen([installer_path], …)` en liste d'args. ✅
- **Path traversal** : `sanitize_order_id()` (`storage.py:35-39`) + `is_valid_order_id()` appliqués partout avant construction de chemin ; couvert par des tests dédiés (path traversal, null byte, backslash). ✅
- **Injection d'URL** : `order_id` sanitisé avant interpolation dans l'URL Chrome → pas d'injection de paramètres. ✅
- **A08 Intégrité** : `download_update()` vérifie le **SHA256** avant de retourner l'installateur, supprime le fichier si mismatch, fail-closed. ✅
- **A09 Logging** : pas de secrets/PII loggués ; `site_url` n'est jamais journalisée. ✅

**Résiduels (faibles) :**
- **A08** : SHA256 et binaire proviennent **tous deux** de la release GitHub → la vérification protège du MITM/corruption mais pas d'une compromission du compte GitHub. La signature Authenticode du binaire serait le cran au-dessus. Ajouter aussi une **allowlist d'host** sur `download_url`/`sha256_url` (cheap defense-in-depth).
- **A02** : EXE non signé + UPX → SmartScreen/antivirus plus susceptibles d'alerter.

---

### 🔗 4. Supply Chain (A03) — Dépendances & CI

**CI : très bonne posture.** Actions épinglées par **SHA complet**, `persist-credentials: false`, permissions **par job** (`contents: read` pour test/build, `contents: write` seulement pour `release`), `pyinstaller` épinglé, **smoke-test de l'EXE** après build. ✅

**Point résiduel — transitives non épinglées.** `requirements.txt` épingle les directes (`==`) mais `idna`, `urllib3`, `certifi`, `charset_normalizer` (listées en `hiddenimports` du `.spec`, donc **embarquées dans l'EXE**) flottent. `pip-audit` (env local) remonte :

```
idna     <3.15   PYSEC-2026-215
urllib3  <2.7.0  PYSEC-2026-141/142
requests 2.33.1  → 2.34.2 dispo (les CVE 2.32.x sont déjà corrigées par le pin actuel)
```

Exploitabilité **faible** (seule surface réseau = HTTPS vers GitHub, réponse vérifiée par SHA256), mais c'est un écart A03 réel : la version transitive embarquée dépend de l'environnement de build. **Recommandations :**
1. Générer un **lockfile complet** (`pip-compile` → `requirements.lock`) installé en CI pour un build reproductible.
2. Ajouter **`pip-audit`** comme étape CI (non bloquante d'abord, puis bloquante).
3. **Merger les 3 PRs Dependabot** ouvertes après passage du build.

---

### 🧩 5. Extension Chrome (MV3)

**Conforme et propre :**
- `manifest_version: 3`, service worker, **CSP explicite** (`script-src 'self'; object-src 'none'`). ✅
- Listeners enregistrés **synchroniquement** au top-level ; nettoyage périodique via **`chrome.alarms`** (pas `setInterval`) ; état dans `chrome.storage.local` (pas de variable globale volatile). ✅
- Aucun `innerHTML`/`eval`, aucun content script injecté, aucune lecture du contenu de page. ✅

**Pistes (faibles) :**
- `host_permissions: ["*://*/wp-admin/admin.php*"]` est probablement **redondant** : l'extension ne fait que `tabs.query`/`tabs.remove` (la permission `tabs` suffit à lire `tab.url` et fermer des onglets). Retirer `host_permissions` réduit l'empreinte de permissions (moindre privilège, et meilleure validation Web Store). À tester rapidement.
- `cleanupTabs()` enchaîne plusieurs `await chrome.storage.local.get/set` par onglet (`untrackTab` en boucle). Volumétrie négligeable ici, mais un seul `set` groupé en fin de cleanup serait plus propre.

---

### 📋 6. Logging & Conformité

`logging_setup.py` : `RotatingFileHandler` 1 Mo × 3, niveau `INFO` (pas de `DEBUG` en prod ✅), pas d'interpolation de données utilisateur non maîtrisées dans les messages sensibles. Les `order_id` journalisés sont déjà sanitisés (pas d'injection CWE-117 réaliste). Pour un poste local mono-utilisateur, le dispositif est **proportionné**. RAS bloquant.

---

## Validation Technique

```
$ python -m pytest tests/ -q
83 passed in 11.54s                      ✅ 100% passants

$ grep -n "urljoin\|from urllib" main.py
1415: url = urljoin(...)                  ❌ utilisé mais jamais importé → NameError avalé

$ grep -rn "shell=True|os.system|pickle.load|yaml.load|eval(|exec(" core/ main.py
(rien sauf exec(stmt) du smoke-test, # noqa)  ✅

$ pip-audit
9 vulnérabilités / 4 paquets — idna, urllib3 (transitifs), requests(env local), pip(build)
                                          ⚠️ transitives non épinglées embarquées

$ gh pr list
#7 numpy >=2.4.6  #6 requests 2.34.2  #5 actions group   ⚠️ 3 Dependabot ouvertes
$ gh repo view → visibility: PUBLIC, licenseInfo: null   ⚠️ public + sans licence
$ gh release list → v1.2.2 (Latest) + v1.2.2 (Draft)     ⚠️ draft résiduel
```

---

## Correctifs Proposés (par priorité)

### Sprint immédiat (impact perf + bug — < 1 jour)
1. **Déporter les overlays** (ROI + REC) du thread de capture vers `_update_frame` (sur l'image 960×540). → latence de détection réduite.
2. **Régler la caméra** : `MJPG` + résolution explicite + `BUFFERSIZE=1` dans `Recorder.start()`. → tester sur C270.
3. **Corriger `urljoin`** : importer `urllib.parse.urljoin` ou supprimer le `try/except` mort.

### Sprint suivant (supply chain + hygiène)
4. **Lockfile complet** + **`pip-audit` en CI** ; merger les 3 PRs Dependabot.
5. **Unifier le build** : `build_win.py` → wrapper de `pyinstaller TMO.spec` (ou suppression).
6. **`upx=False`** dans `TMO.spec` (réduction faux positifs AV + démarrage) ; planifier la signature de l'EXE.
7. Ne redémarrer la caméra dans `_apply_config` **que si** l'index/flip a changé.

### Backlog
8. Allowlist d'host sur les URLs de l'updater ; à terme, signature indépendante du binaire.
9. Extension : retirer `host_permissions` si redondant (à valider).
10. Repo : confirmer la visibilité publique / ajouter une LICENSE ; supprimer la release draft v1.2.2.

---

## Suivi de la revue v1 (vérifié dans le code)

| Item v1 | État actuel |
|---------|-------------|
| Actions GitHub non épinglées | ✅ Toutes épinglées par SHA + `persist-credentials: false` |
| `requirements.txt` non épinglé | ✅ Directes épinglées `==` (+ `numpy` ajouté) |
| Installateur sans vérif intégrité | ✅ SHA256 vérifié dans `download_update()`, fail-closed |
| Permissions CI trop larges | ✅ Split test/build (`read`) vs release (`write`) |
| Logging absent | ✅ `logging_setup.py` + events structurés |
| `setTimeout` dans le SW MV3 | ✅ Remplacé par `await cleanupTabs()` immédiat + `chrome.alarms` |
| QR disable permanent | ✅ Compteur `_qr_error_count` + seuil 10, reset sur succès |
| CSP manifest absente | ✅ `content_security_policy` présent |
| Échec silencieux config.json | ✅ `load_config()` → tuple + dialog d'alerte |
| Pas de tests | ✅ 4 fichiers, 83 tests passants |

**Conclusion :** la base est saine et la dette de sécurité de v1 est soldée. Les gains les plus utiles sont désormais **opérationnels** (latence de détection QR) plutôt que sécuritaires.
