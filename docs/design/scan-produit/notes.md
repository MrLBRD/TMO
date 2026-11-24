# Scan produit pendant la préparation : notes et sources (révision du 24/11)

Lot BF des retours terrain du 24/11/2026. Proposition seule, aucun code. Maquette : `maquette.html`.

Réponses d'Arnaud intégrées : les codes `2019…` ne sont pas collés sur les produits et ne le seront jamais ; un canal TMO ↔ site avec clé est accepté (et il se demande s'il peut aussi porter le raccourci d'impression).

## 1. Ce qui existe aujourd'hui

- **Douchette** : TMO reçoit le scan (clavier HID avec focus, ou port série sans focus). `_start_from_raw()` (`main.py`) ne comprend que `Tk-{id}` et `TK2:{id}:{transporteur}:{sku*qty,...}` (`core/storage.py::parse_qr_value`). Le bloc articles du TK2 est lu puis jeté.
- **Un EAN scanné aujourd'hui** : un EAN-13 dépasse 10 caractères, TMO répond « ID commande invalide » et ne fait rien. Un code de 5 à 10 chiffres (les 12 lignes à EAN court du catalogue) ouvre la boîte « Code sans préfixe », qui peut démarrer un enregistrement pour une fausse commande.
- **Ticket** (TicketPrinter) : le QR/Data Matrix TK2 porte le SKU et la quantité de chaque ligne, pas l'EAN. Le texte imprimé par article : `x{qté} nom`, `Ref : … - EAN : …`, `[taille]`, options. Le payload contient déjà `EAN`, `sku`, `reference`, `size`, `qty` (moins les remboursements) par article (`class-ticket-generator.php:660-725`, contrat `schema/ticket-payload-contract.md`).
- **Où vit l'EAN** : méta `_alg_ean` (extension `ean-for-woocommerce`), posée sur la **variation** vendue. Le ticket lit `_alg_ean`, puis `ean`, puis `_ean`. La page de contrôle WCBM (`orders-processing.php:1018`) essaie 20 clés et retombe sur la variation. WooCommerce a aussi son champ natif `_global_unique_id` (28 269 variations).
- **Page de contrôle** (`?orderCheck=ID`, WCBM `order-check.js`) : affiche déjà photo, nom, taille, EAN et quantité par article. Il lui manque seulement la validation.
- **Pas de canal authentifié** entre TMO et le site aujourd'hui : TMO ne fait qu'ouvrir Chrome (connecté à wp-admin) et l'extension relaie. Pas de clé API dans `config.py`.

## 2. Comment le scan marcherait

1. Ticket scanné : comme aujourd'hui (vidéo + commande). En plus, TMO demande au site la liste des articles de la commande (une requête).
2. Chaque scan suivant sans préfixe `Tk-`/`TK2:` est un scan produit, jamais une nouvelle commande. Un code de 8 à 14 chiffres hors ticket suit ce chemin (fin de la boîte « Code sans préfixe » pour ces codes).
3. Comparaison : EAN scanné contre les EAN attendus. Normalisation obligatoire : l'UPC-A de 12 chiffres est lu comme EAN-13 avec un zéro devant (1 011 lignes vendues sont en 12 chiffres, soit 21 %). On compare les chiffres sans zéros de tête.
4. Verdict en grand (écran maquette) : OK, encore N, pas dans la commande, bon modèle mauvaise taille, déjà tout scanné, regarde l'article (sans code). Un bip distinct par famille (court OK, long KO).
5. La vidéo continue quoi qu'il arrive. Une erreur de contrôle (site injoignable) n'arrête jamais l'enregistrement : l'écran dit « contrôle indisponible » et l'opérateur travaille comme avant.
6. Trace : chaque scan (heure, code, verdict) dans `tmo.log` et dans un petit fichier à côté de la vidéo, pour retrouver un litige.
7. Commande complète : l'écran passe au vert. Le scan du ticket suivant arrête la vidéo, comme aujourd'hui. Rien n'est bloquant : l'opérateur peut passer outre (le contrôle informe, il n'empêche pas, comme le verrou de présence WCBM).

**Où se fait la comparaison** : TMO appelle le site (colonne 1, retenue par la réponse d'Arnaud sur la clé).

| | TMO appelle le site (recommandé) | Page WCBM pilotée par TMO | EAN dans le QR (TK3) |
|---|---|---|---|
| Écran | fenêtre TMO, déjà devant l'opérateur | page Chrome | fenêtre TMO, sans noms ni tailles |
| Données | noms, tailles, photos, « taille 43 » | idem | codes seulement |
| Nouveau canal | clé API + une route WCBM en lecture | TMO → extension par URL à chaque scan : onglet qui clignote, focus volé | aucun |
| Mauvaise taille | oui (recherche de l'EAN dans le catalogue) | oui | non |
| Hors ligne | non (repli : contrôle indisponible) | non | oui |

« Mauvaise taille » demande de savoir à quel produit appartient un EAN absent de la commande : seul le catalogue le sait. Sans cela, on ne sait dire que « pas dans cette commande ».

## 3. Chiffres de couverture (labo, copie anonymisée de la prod au 24/11/2026)

Fenêtre : 90 jours jusqu'au 24/11/2026, commandes processing, completed et on-hold, hors méta `_uc_lab`, quantités moins remboursements : **4 059 commandes, 4 676 lignes, 8 931 pièces**. (Les chiffres de la première version, 4 138 commandes, comptaient aussi des commandes entièrement remboursées.) EAN du labo = vrais EAN (copie de `_alg_ean` par la synchro).

« Scannable » = EAN-13 fabricant ou UPC-A de 12 chiffres dans `_alg_ean` de la variation vendue. Pas scannable = code `2019…` (jamais collé, réponse d'Arnaud), vide, trop court ou trop long.

| Commandes | Nombre | Part | Pièces | Part des pièces |
|---|---|---|---|---|
| **Entièrement scannables** (tous les articles ont un EAN fabricant) | 3 285 | **80,9 %** | 3 956 | 44,3 % |
| Mixtes (au moins un scannable et un non) | 77 | 1,9 % | 941 | 10,5 % |
| **Rien de scannable** | 697 | **17,2 %** | 4 034 | 45,2 % |

| Lignes et pièces | Lignes | Pièces |
|---|---|---|
| Scannables | 3 772 (80,7 %) | 4 087 (45,8 %) |
| Non scannables | 904 (19,3 %) | 4 844 (54,2 %) |

Lecture :
- **Par commande, le scan marche pour 81 %.** Par pièce, seulement 46 %, parce que les lignes `2019…` sont lourdes : 5,4 pièces en moyenne, contre 1,1 pour un code fabricant.
- **137 commandes de 12 pièces ou plus** (3 % des commandes) portent 3 897 pièces non scannables, soit 43 % de toutes les pièces : commandes de club, crampons de rechange à l'unité. Pour ces lots, aucun scan ne compte les pièces : on affiche la quantité en grand, l'opérateur compte et clique.
- **Les 697 commandes « rien de scannable »** ont presque toutes une seule ligne (1,14 en moyenne) pour 5,8 pièces : le scan n'y apporterait rien, la confirmation visuelle est le seul contrôle.
- Sur les 2 % mixtes (77 commandes, 2,9 lignes), la moitié des gestes est un scan, l'autre un clic.
- Lignes non scannables par commande : 0 pour 3 285 commandes, 1 pour 663, 2 pour 99, 3 ou plus pour 12. Le cas courant est donc une seule confirmation visuelle.

Les chiffres de la première version restent valables pour les 0,4 % de lignes sans aucun code (17 lignes : casque Adidas, cartes cadeaux, protège-dents, gilets Propadz).

## 4. Est-ce que le contrôle vaut encore le coup ?

Oui, sous cette forme, et pas davantage.

1. **Avec code (81 % des commandes entières, 46 % des pièces)** : scan. C'est un vrai contrôle automatique du modèle et de la taille.
2. **Sans code (`2019…`, vide)** : confirmation visuelle en un clic. L'écran montre la photo de la variation commandée, la taille en très gros (écran F de la maquette) et, si la quantité dépasse 1, la quantité en très gros (écran G). L'opérateur compare avec le produit dans ses mains et clique « C'est bon ». Le clic est tracé (heure, ligne, poste).
3. **Ce que le contrôle ne garantit pas** : un clic ne prouve rien, il oblige à regarder. Pour les 54 % de pièces en visuel, le gain est celui d'un rappel (photo, taille) et d'une trace, pas d'une vérification automatique. C'est un contrôle moins fort que le scan, à dire à Arnaud tel quel.
4. **Chiffre qui manque** : le nombre d'erreurs de préparation aujourd'hui (mauvaise taille, mauvais modèle). Sans lui, on ne peut pas dire combien d'erreurs le scan évitera. Une piste : compter, dans les retours et le SAV de WCBM, les motifs « erreur de préparation » sur 90 jours (à faire dans le labo).
5. Le contrôle n'est pas bloquant : l'opérateur passe outre, la vidéo continue.

Écarté : code-barres par article sur le ticket (contrôle la ligne du ticket, pas le produit) et étiquetage interne des produits (refusé par Arnaud pour les `2019…`).
Écarté aussi : écrire un faux EAN dans `_alg_ean`. Cette méta part vers Lengow, Decathlon et Amazon.

**Amélioration au fil de l'eau** : à un « C'est bon » sur un article sans code fabricant, proposer de saisir l'EAN lu sur la boîte (champ « EAN » sur la ligne). Les 806 variations sans EAN et celles en `2019…` qui ont une vraie boîte se comblent par l'usage.

## 5. Piste d'Arnaud : un canal TMO ↔ site avec une clé

### 5.1 Comment le raccourci d'impression marche aujourd'hui

1. Le mini-clavier 3 touches (HID, mémoire embarquée) envoie `Alt+Shift+P` (touche fixe).
2. **Extension Chrome de TMO** (`chrome_extension/`) : `background.js` capte la touche hors focus (`chrome.commands`, `global: true`), trouve l'onglet de la commande (`findPrintTarget()` : l'onglet du dernier `orderCheck`, sinon le plus récent des onglets TMO, sinon n'importe quel onglet WCBM), lui envoie un message ; `content_script.js` émet l'événement DOM `tmo-print-request`.
3. **WCBM** (`order-check.js`, `printRequestHandler`) écoute l'événement et clique le bouton « Générer étiquette » de la modale. Le toast « Raccourci reçu (…) » existe parce que c'était invérifiable autrement.
4. Le clic lance la génération côté serveur (API DPD ou Boxtal), puis **l'impression se fait dans Chrome** : DPD télécharge un fichier DAT dans un iframe caché (le Station DPD le traite), Boxtal ouvre une popup `window.open` et appelle `window.print()` sous `--kiosk-printing`. La popup demande un focus et une activation utilisateur : le code reconnaît que l'extension doit forcer le focus de l'onglet, et un filet « Popup bloquée » (`LabelRecovery`) rattrape l'échec.
5. TicketPrinter n'est pas dans ce chemin : il imprime le ticket de caisse, pas l'étiquette transporteur.

L'extension a trois autres rôles : fermer les anciens onglets, rouvrir la commande dans l'onglet déjà chargé (`reuse.js`, évite de recharger 120 scripts), et le raccourci « onglet actif ».

### 5.2 Les trois solutions

| | A. Extension seule (aujourd'hui) | B. Clé pour le contrôle, extension pour l'impression | C. Clé pour tout : TMO déclenche l'impression |
|---|---|---|---|
| Contrôle des produits | impossible proprement (pas de données dans TMO) | oui (articles et recherche d'EAN) | oui |
| Raccourci d'impression | extension (hors focus + onglet actif) | extension, inchangée | **TMO capte la touche** (hotkey Windows) et appelle le site |
| Ce qui se simplifie | rien | rien côté impression ; fin des idées d'EAN dans le QR | plus de `findPrintTarget()`, de message de l'extension, de focus d'onglet ; plus d'impression qui dépend de l'onglet visible |
| Ce qui casse ou se complique | n/a | rien | **l'impression elle-même** : DAT DPD et popup `window.print()` vivent dans le navigateur. TMO devrait télécharger l'étiquette et l'envoyer à l'imprimante lui-même (nom d'imprimante, DAT vers Station DPD). Retours d'erreur (popup bloquée, anti-spam, écart de transporteur, cooldown) à refaire hors de la modale. |
| Extension Chrome | reste | reste | **reste quand même** : fermeture et réutilisation d'onglets, et la page de contrôle reste dans Chrome |
| Travail | 0 | moyen | élevé et risqué : l'impression d'étiquettes est le geste critique du poste |

### 5.3 Ma recommandation

**B maintenant, C seulement après.** La clé est utile dès ce lot (liste d'articles et recherche d'EAN). Le raccourci d'impression passe par TMO plus tard, et seulement si l'impression est aussi sortie du navigateur : sinon on remplace un relais simple (extension → page) par un relais plus long (TMO → site → TMO → imprimante) sans rien gagner, et l'extension reste. Ce que C supprimerait vraiment, ce sont les cas où l'onglet n'a pas le focus ou la popup est bloquée. Si ce sont des pannes fréquentes au poste, C devient un lot à part, avec ses propres tests sur le matériel.

### 5.4 Ce que demande la clé (identique pour B et C)

- **Forme** : mot de passe d'application WordPress (natif, révocable, HTTPS obligatoire) pour un utilisateur dédié « poste TMO », une clé par poste. Aucun code d'authentification à écrire côté site. À vérifier en prod : mots de passe d'application non désactivés, HTTPS partout (le labo est en HTTP, il répond « indisponible » : sans signification pour la prod). Une clé maison signée (HMAC) serait la solution de repli, plus de code.
- **Droits** : un rôle minimal avec une capacité propre « TMO » (lecture des articles d'une commande, recherche d'EAN, pas d'écriture). Pour C, une capacité d'impression en plus.
- **Côté TMO** : champ « Clé » dans les réglages, stockée dans le coffre Windows (pas en clair dans `config.json`), jamais écrite dans `tmo.log`. Le journal ne contient pas l'URL avec clé.
- **Prod** : création de l'utilisateur et de la clé par Arnaud (geste en prod). Jamais de clé dans un dépôt.
- **Panne** : si le site ne répond pas, TMO affiche « contrôle indisponible » et l'enregistrement continue. Pour C, le repli doit rester le raccourci de l'extension.

## 6. Ce que ça demanderait en code

**TMO** (B)
- `core/storage.py` : reconnaître un scan produit (8 à 14 chiffres hors ticket) ; normaliser UPC-A et EAN-13 (zéros de tête) ; plus de boîte « Code sans préfixe » pour ces codes.
- Module de contrôle : articles de la commande, compteurs par ligne, verdicts, bips, trace ; écrans de la maquette (A à H) dans l'overlay.
- Client HTTP avec la clé, délais courts, repli « contrôle indisponible ». Tests des verdicts, de la normalisation et du repli. Version synchronisée sur les 3 fichiers.
- Pour C en plus : hotkey global Windows, téléchargement de l'étiquette, impression locale, gestion d'erreurs.

**WCBM**
- Route en lecture : articles d'une commande `{ligne, sku, ean, nom, taille, quantité à préparer, photo, id parent}` avec les règles du ticket (quantité moins remboursements, ligne remboursée retirée) et un drapeau `scannable` calculé côté site (EAN-13 ou UPC-A hors `2019…`).
- Route de recherche EAN → produit parent et taille, pour « bon modèle, mauvaise taille ». Index sur `_alg_ean` si la requête est lente.
- Rôle et capacité « TMO ». Journal des clics « C'est bon » (note de commande ou audit).
- Pour C en plus : route de génération et de récupération d'étiquette sans passer par la modale.

**TicketPrinter** : rien, dans B comme dans C.

## 7. Questions pour Arnaud

1. Les pannes du raccourci d'impression (onglet sans focus, popup bloquée) arrivent-elles souvent ? Si non, B suffit.
2. Qui crée l'utilisateur et la clé en prod, et OK pour une clé par poste ?
3. Combien d'erreurs de préparation par mois aujourd'hui ? Cela donne le gain réel du scan.

## 8. Limites

- Chiffres du labo : copie de la prod au 24/11, synchro nocturne, pas lecture directe de la prod.
- La maquette utilise des pictogrammes à la place des photos produit. Noms, tailles et codes y sont inventés ; seuls les chiffres du bloc 3 sont réels.
- Je n'ai pas mesuré le nombre d'erreurs de préparation actuelles.
