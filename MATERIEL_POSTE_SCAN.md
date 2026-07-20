# Investissement matériel — poste de scan TMO

> Document d'aide à la décision. Rédigé le 2026-07-20.
> Les estimations de gain sont des ordres de grandeur à valider par mesure, pas des chiffres constatés.

---

## 1. Contexte

Deux problèmes distincts ont été identifiés sur le poste de scan :

| Problème | Nature | Statut |
|---|---|---|
| Vidéo accélérée et saccadée | Logiciel | **Corrigé** (voir §2) |
| Le scan QR échoue 2 à 3 fois avant de passer | Matériel | Ouvert — objet de ce document |

Matériel actuel : webcam **Logitech C270** (focus fixe, rolling shutter, entrée de gamme), éclairage d'atelier existant non caractérisé.

---

## 2. Ce qui a déjà été corrigé (sans coût matériel)

Le MP4 était ouvert avec `CAP_PROP_FPS`, c'est-à-dire le débit **déclaré** par la webcam (30 fps), alors que la caméra n'en livrait réellement que 10 à 15 — l'auto-exposition allonge le temps de pose quand la lumière manque, et le capteur ralentit d'autant. On écrivait donc ~10 images dans un conteneur estampillé 30 fps, d'où une lecture ~3× accélérée.

Correctif appliqué dans `core/recorder.py` :

- **Mesure du débit réel** (`_record_frame_time`, `_effective_fps`) — moyenne glissante sur 90 frames, amorcée par un warm-up à l'ouverture de la caméra. C'est cette valeur qui est inscrite dans le MP4.
- **Écriture à cadence constante** (`_writer_loop`) — chaque frame occupe autant de slots que sa durée réelle l'exige, calculée sur son timestamp. La durée du fichier reste exacte même si le débit varie pendant l'enregistrement.

Un log `camera_fps measured=… declared=…` est écrit dans `tmo.log` au démarrage puis chaque minute. **Cette valeur `measured` est le premier chiffre à relever** : elle caractérise l'éclairage actuel du poste.

---

## 3. Diagnostic : d'où viennent les 2-3 tentatives de scan

Par ordre de probabilité décroissante :

1. **Flou de bougé.** En lumière faible, la pose s'allonge (même mécanisme que la chute de fps). Un ticket qui bouge pendant 1/15 s produit un QR flou, donc illisible. **Corrigé par l'éclairage.**
2. **Focus fixe de la C270.** Elle ne fait le point que dans une plage étroite ; un ticket présenté trop près est flou en permanence. **Corrigé par une caméra autofocus.**
3. **Rolling shutter.** Le capteur lit l'image ligne par ligne : un ticket en mouvement rapide se déforme en biais. **Corrigé uniquement par un capteur global shutter.**

> Les causes 1 et 2 sont les plus probables et se traitent à bas coût. La cause 3 ne devient dominante qu'une fois les deux premières éliminées — c'est ce qui structure les deux options ci-dessous.

---

## 4. Prérequis commun aux deux options : l'éclairage

**À faire en premier dans les deux scénarios.** C'est le seul poste qui améliore simultanément la détection QR, la qualité de la vidéo de preuve, le débit d'images et le confort de l'opérateur.

### Critères d'achat

| Critère | Valeur cible | Pourquoi |
|---|---|---|
| **Sans scintillement** (driver DC, « flicker-free ») | Impératif | Un driver PWM bas de gamme produit des bandes qui défilent à l'image et peut faire échouer la détection QR. **Critère n°1, systématiquement ignoré à l'achat.** |
| IRC / CRI | ≥ 90 | Fidélité des couleurs des produits sur la vidéo de preuve |
| Température | 4000 K (blanc neutre) | Moins fatigant que le 6500 K froid, meilleur rendu que le 3000 K chaud |
| Diffuseur | Opale, jamais de LED nue | Évite les reflets spéculaires sur les tickets brillants, qui gênent le scan |
| Éclairement au plan de travail | 750–1000 lux | Un poste d'emballage tourne souvent à 200–300 lux ; un travail de lecture/vérification en demande 750–1000 |
| Nombre de points lumineux | 2 | Supprime l'ombre portée de la main de l'opérateur sur le ticket |

### Coût

**~60 € par réglette × 2 = ~120 €**

### Bénéfice annexe

Réduction de la fatigue oculaire de l'opérateur — bénéfice réel indépendant du sujet technique.

---

## 5. Option A — Mono-capteur

Une seule caméra assure les deux rôles : scanner le QR **et** produire la vidéo de preuve.

### Matériel

| Poste | Modèle | Prix constaté |
|---|---|---|
| Éclairage | 2 réglettes LED (critères §4) | ~120 € |
| Caméra | **Logitech C922 Pro** | 50–60 € |
| Fixation | Bras articulé (filetage 1/4") | ~20 € |
| | **Total** | **~200 €** |

### Pourquoi la C922 dans cette configuration

- **Trépied 1/4" fourni** — montage sur bras articulé, positionnement précis au-dessus de la zone de scan. Critère décisif pour un poste fixe.
- **Autofocus** — élimine la cause n°2 du diagnostic (le point faible majeur de la C270).
- **720p/60** — l'app tourne en 720p par défaut, la marge de débit est confortable.
- **Maturité DirectShow/OpenCV** — une décennie de retours d'expérience. Le code force MJPG et manipule les `CAP_PROP_*` : ce n'est pas anecdotique.
- Champ de 78°, fixe.

### Ce que cette option ne résout pas

Le rolling shutter subsiste. Si les tentatives de scan restent élevées après éclairage + C922, la cause résiduelle est là.

### Limite structurelle

Un capteur unique impose un compromis entre deux besoins contradictoires :

| Bien scanner veut | Une bonne vidéo de preuve veut |
|---|---|
| Pose courte (fige le mouvement) | Pose plus longue (image lumineuse) |
| Contraste dur | Couleurs fidèles |
| Cadrage serré sur la zone de scan | Champ large (tout le plan de travail) |
| Fréquence élevée | Résolution |

Ces réglages s'excluent mutuellement. Toute configuration mono-capteur est un compromis, pas un optimum.

---

## 6. Option B — Bi-capteur

Un capteur dédié au scan, un capteur dédié à la vidéo. Chacun optimisé pour son rôle, sans compromis.

### Matériel

| Poste | Modèle | Prix |
|---|---|---|
| Éclairage | 2 réglettes LED (critères §4) | ~120 € |
| Caméra vidéo | **Logitech Brio 500** | ~80 € |
| Capteur scan | Module USB UVC global shutter (Arducam / ELP, capteur AR0234 ou IMX296) | **~60–120 $ — à confirmer**, prix non trouvés en source fiable |
| Fixation | 2 bras articulés | ~40 € |
| | **Total** | **~300–350 €** |

### Pourquoi la Brio 500 devient le bon choix ici — et pas en option A

Le choix s'inverse dès que la caméra est déchargée du rôle de scan :

- **Champ réglable 65/78/90°** — devient le critère n°1. À 70 cm de distance de montage : ~1 m de largeur couverte à 78° (C922) contre ~1,20 m à 90° (Brio). Une preuve qui coupe les bords du plan de travail est une preuve incomplète.
- **HDR / RightLight 4** — *nuisibles* en option A (le tone-mapping lisse le contraste local dont `pyzbar` a besoin), ils deviennent un **atout** sur une caméra qui ne fait que filmer : meilleure gestion d'un poste mêlant zone éclairée et zones d'ombre.
- **RightSight (auto-framing)** — à désactiver une fois via Logi Options+, sans conséquence ensuite.
- Ce qu'on perd n'a plus d'importance : autofocus rapide (scène à distance fixe) et 720p/60 (une vidéo de preuve n'en a pas besoin).

### Pourquoi un module global shutter pour le scan

Le capteur capture toute l'image au même instant : le QR reste carré même présenté en mouvement. Les modules Arducam/ELP sont en **UVC standard**, donc directement compatibles avec `cv2.VideoCapture` sans pilote. La documentation Arducam mentionne explicitement le scan de codes-barres/QR en logistique et packaging.

Ces modules offrent en outre un contrôle manuel complet de l'exposition et, sur certains, des objectifs M12 interchangeables — on choisit la focale adaptée à la distance de présentation du ticket, et le point ne bouge plus jamais.

### Pourquoi ne pas mettre le module global shutter sur la vidéo

Petit capteur, pas de traitement d'image, parfois monochrome. Excellent pour le scan, médiocre pour un livrable qui doit rester lisible et exploitable comme preuve. D'où la séparation des rôles.

---

## 7. Comparatif

| | Option A — Mono-capteur | Option B — Bi-capteur |
|---|---|---|
| Coût total | **~200 €** | **~300–350 €** |
| Traite le flou de bougé | Oui (éclairage) | Oui (éclairage) |
| Traite le focus fixe | Oui (autofocus) | Oui |
| Traite le rolling shutter | **Non** | **Oui** |
| Qualité de la vidéo de preuve | Bonne, champ 78° fixe | Meilleure, champ jusqu'à 90° + HDR |
| Optimisation des deux rôles | Compromis structurel | Optimum sur chaque rôle |
| Risque technique | Faible | Bande passante USB à valider (§9) |

---

## 8. Gains estimés

> **Estimations, pas des mesures.** Hypothèses : 2,5 tentatives de scan en moyenne aujourd'hui, ~2,5 s par tentative, 250 jours ouvrés/an. À recalculer sur les chiffres réels.

### Option A — hypothèse : passage de 2,5 à ~1,3 tentative

Gain ≈ 3 s par ticket.

| Volume | Tickets/an | Gain annuel |
|---|---|---|
| 100 tickets/jour | 25 000 | ~21 h |
| 200 tickets/jour | 50 000 | ~42 h |
| 400 tickets/jour | 100 000 | ~83 h |

### Option B — gain marginal supplémentaire, hypothèse : passage de ~1,3 à ~1,0 tentative

Gain additionnel ≈ 0,75 s par ticket.

| Volume | Tickets/an | Gain annuel additionnel |
|---|---|---|
| 100 tickets/jour | 25 000 | ~5 h |
| 200 tickets/jour | 50 000 | ~10 h |
| 400 tickets/jour | 100 000 | ~21 h |

### Lecture

**L'essentiel du gain est dans l'option A**, parce qu'elle traite les deux causes les plus probables. L'option B capture le résidu — significatif à fort volume, marginal en dessous de ~200 tickets/jour.

Ces chiffres ne valent que si le diagnostic §3 est correct. **Il faut mesurer.**

---

## 9. Recommandation

**Séquence : éclairage + C922 d'abord (~200 €), mesure sur une semaine, puis décision sur l'option B.**

Raisons :

1. L'éclairage est le seul poste qui améliore tout à la fois, et il conditionne le diagnostic. Il n'y a aucun scénario où on ne le fait pas.
2. Éclairage + autofocus traitent les deux causes les plus probables. Il est plausible que les tentatives tombent à 1 et que l'affaire soit close pour 200 €.
3. Si 2 tentatives systématiques subsistent après ça, les causes bon marché sont éliminées : le global shutter adresse alors bien le résidu, avec certitude au lieu d'un pari.

### Nuance sur le choix de caméra

Si tu considères l'option B comme **probable et proche**, achète directement la **Brio 500** plutôt que la C922 : elle sera la bonne caméra dans la configuration finale, et reste acceptable en attendant. Cela évite de racheter une caméra dans six mois.

Critère concret pour trancher : **mesurer la largeur de la zone à filmer et la distance de montage disponible.** Zone < 1 m avec du recul → les 78° de la C922 suffisent, économie de 25 €. Poste large ou caméra proche → la Brio 500 s'impose.

---

## 10. À vérifier avant de commander

- [ ] **Fixation de la Brio 500** — conçue pour se clipser sur un écran ; l'existence d'un filetage 1/4" standard n'est **pas confirmée**. Bloquant pour un montage sur bras articulé. Vérifier sur la fiche produit ou une photo du dessous.
- [ ] **Bande passante USB (option B uniquement)** — deux caméras UVC sur le même contrôleur peuvent saturer et refuser de fonctionner simultanément. Les répartir sur des contrôleurs distincts (pas deux ports du même hub) et rester en MJPG. **Testable en cinq minutes avec deux webcams quelconques avant d'engager le budget.**
- [ ] **Prix réel des modules global shutter** — non confirmés par une source fiable, à relever chez les revendeurs.
- [ ] **Relever `measured` dans `tmo.log`** — caractérise l'éclairage actuel et donne le point de comparaison avant/après.

---

## 11. Impacts logiciels

À prévoir une fois le matériel en place :

- **Relancer la calibration QR** (bouton dans la config, `calibrate_qr`). Les réglages brightness/contrast actuels sont optimisés pour le capteur et l'éclairage d'aujourd'hui ; ils seront à côté de la plaque après changement.
- **Vérifier `camera_index`** — brancher une nouvelle caméra peut décaler l'index OpenCV.
- **Arbitrer `camera_width` / `camera_height`** — passer à 1920×1080 est possible mais alourdit `pyzbar` et l'encodage. Acheter du 1080p pour tourner en 720p n'apporte rien ; le faire tourner en 1080p au prix du fps non plus. À décider sur mesure.
- **Option B — refonte du `Recorder`** : deux `VideoCapture` et deux threads de capture, dédoublement de `camera_index` en config, choix de la source affichée dans l'aperçu, restriction de la calibration QR à la seule caméra de scan.

---

## 12. Instrumentation proposée

Pour disposer du chiffre avant/après sans manipulation pour l'opérateur :

- **Compteur de tentatives par scan affiché dans l'UI** — lisible en passant devant le poste.
- **CSV cumulatif écrit dans `output/`** — dossier déjà consulté, aucun fichier à extraire du poste.

Mesures utiles : délai entre la première détection d'un QR dans le champ et le décodage exploitable, et nombre de frames où un QR était visible mais non décodé.

C'est ce qui permettra de valider ou d'invalider les estimations du §8 — et de décider de l'option B sur des chiffres plutôt que sur des hypothèses.
