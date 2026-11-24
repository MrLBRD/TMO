# Scan produit pendant la préparation : notes et sources

Lot BF des retours terrain du 24/11/2026. Proposition seule, aucun code. Maquette : `maquette.html`.

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

**Où se fait la comparaison** (décision technique) :

| | TMO appelle le site (recommandé) | Page WCBM pilotée par TMO | EAN dans le QR (TK3) |
|---|---|---|---|
| Écran | fenêtre TMO, déjà devant l'opérateur | page Chrome | fenêtre TMO, sans noms ni tailles |
| Données | noms, tailles, photos, « taille 43 » | idem | codes seulement |
| Nouveau canal | clé API + une route WCBM en lecture | TMO → extension par URL à chaque scan : onglet qui clignote, focus volé | aucun |
| Mauvaise taille | oui (recherche de l'EAN dans le catalogue) | oui | non |
| Hors ligne | non (repli : contrôle indisponible) | non | oui |

« Mauvaise taille » demande de savoir à quel produit appartient un EAN absent de la commande : seul le catalogue le sait. Sans cela, on ne sait dire que « pas dans cette commande ».

## 3. Chiffres de couverture (labo, copie anonymisée de la prod au 24/11/2026)

Fenêtre : 26/08 → 24/11/2026, commandes processing, completed et on-hold, hors méta `_uc_lab` (384 exclues). 4 138 commandes, 4 732 lignes, 8 992 pièces (quantités moins remboursements). Les EAN du labo sont les vrais (copie `_alg_ean` par la synchro nocturne).

| Code sur la variation vendue | Lignes | Pièces |
|---|---|---|
| EAN-13 fabricant | 2 811 (59 %) | 3 105 (35 %) |
| UPC-A 12 chiffres (lisible, avec normalisation) | 1 011 (21 %) | 1 036 (12 %) |
| **Code interne `2019…` (13 chiffres)** | **893 (19 %)** | **4 834 (54 %)** |
| Aucun code utilisable : vide 3, court 12, trop long 2 | **17 (0,4 %)** | 17 |

- **Vraiment sans code : 0,4 % des lignes, 15 à 17 commandes sur 4 138.** Casque Adidas (QR GS1 collé dans la méta), cartes cadeaux, protège-dents, gilets Propadz (codes de 10 chiffres sans clé), un T-shirt. Sept produits au total.
- **Codes `2019…` : 19 % des lignes, mais 54 % des pièces.** Ce sont des codes internes (préfixe GS1 « 20 », usage restreint), 9 749 variations, 2 117 produits, clé valide dans 9 738 cas. Marques : Under Armour, Adidas, Kappa, Budgy Smuggler, Impact. Ces lignes portent 5,4 pièces en moyenne, contre 1,1 pour un code fabricant (crampons de remplacement à l'unité, commandes de club). **Je ne sais pas si ce code est collé sur les produits** (étiquette SPERO ?). C'est la vraie question du lot.
- 780 commandes sur 4 138 (19 %) ont au moins une ligne en `2019…` ou sans code : c'est la part de commandes que le scan ne couvrirait pas entièrement si ces codes ne sont pas sur les produits.
- EAN partagé par plusieurs fiches : 9 valeurs, 17 lignes vendues (27 pièces). Sans effet sauf deux tailles dans la même commande.
- Catalogue : 2 368 produits, 39 095 variations dont 806 sans `_alg_ean` (160 parents) et 4 produits simples sans EAN. 6 320 fiches ont un code de 12 chiffres.
- Par canal : presque tout vient du site (2 358 lignes) et du checkout (1 768) ; les marketplaces pèsent quelques lignes.
- La synchro prod copie seulement `_alg_ean` et `_global_unique_id` : un EAN rangé ailleurs en prod n'apparaît pas ici. La méta réellement utilisée est `_alg_ean` (le ticket ne lit rien d'autre que `_alg_ean`, `ean`, `_ean`).

## 4. Produits sans code : solutions comparées

Deux populations différentes, donc deux réponses.

**A. Les 0,4 % sans aucun code (17 lignes)**

| Solution | Principe | Ce que ça prouve | Coût | Avis |
|---|---|---|---|---|
| **Un clic** | Ligne ambrée « regarde l'article », bouton « C'est bon ». Le clic est tracé (heure, opérateur). | Que l'opérateur a regardé. | Aucun stock à toucher. Un bouton. | **Recommandé** |
| Code-barres par article sur le ticket | Un Code 128 du SKU sous chaque ligne ; on scanne la ligne. | Que la ligne du ticket a été vue, pas le produit. | Ticket plus long (≈ 10 à 14 mm par ligne), bwip-js déjà dans l'app, largeur 225 px. | Non : contrôle sans valeur |
| EAN interne généré | Code `2019…` (préfixe 20) posé dans une méta à part et étiqueté en rayon. | Le produit réel. | Impression et collage, pour 7 produits. | Disproportionné |

**B. Les 19 % en code `2019…`**

- Si le code est déjà collé sur les produits : rien à faire, le scan marche tel quel (c'est déjà l'« EAN interne »).
- S'il n'est pas collé : imprimer l'étiquette avec le code **qui existe déjà** (pas de génération), au rangement du stock, produit par produit en commençant par les plus vendus. En attendant : « un clic ».
- À ne pas faire : écrire un faux EAN dans `_alg_ean`. Cette méta part vers Lengow, Decathlon et Amazon, et la règle Decathlon exclut déjà les 5 codes factices connus (`2019000363068`…). Tout code interne nouveau va dans une méta à part.

**Remplissage au fil de l'eau** : à chaque « un clic » sur un article sans code, proposer de saisir l'EAN lu sur la boîte (champ « EAN » sur la ligne). Le trou se comble par l'usage.

## 5. Ce que ça demanderait en code

**TMO**
- `core/storage.py` : reconnaître un scan produit (8 à 14 chiffres hors ticket) ; normaliser UPC-A/EAN-13 ; ne plus ouvrir la boîte « Code sans préfixe » pour ces codes.
- Nouveau module de contrôle : liste d'articles de la commande, compteurs par ligne, verdicts, bips, trace.
- Client HTTP vers le site avec clé API (réglage TMO) ; repli « contrôle indisponible ».
- `main.py` : zone « contrôle » dans l'overlay (maquette), bouton « C'est bon ». Tests des verdicts et de la normalisation. Version sur les 3 fichiers.

**WCBM**
- Route en lecture (REST ou AJAX à clé) : articles d'une commande `{ligne, sku, ean, nom, taille, qté à préparer, photo, id parent}` avec les mêmes règles que le ticket (quantité moins remboursements, ligne remboursée retirée).
- Recherche EAN → produit parent et taille, pour « bon modèle, mauvaise taille ». Index ou requête sur `_alg_ean`.
- Gestion de la clé (réglage admin, droits minimaux). Retour du « un clic » en note de commande ou journal.

**TicketPrinter**
- Rien d'obligatoire. Option : ajouter l'EAN (ou le SKU) au Data Matrix si on choisit l'EAN dans le QR (TK3) ; contrat `ticket-qr-contract.md` à changer en premier.

## 6. Questions pour Arnaud

1. Les codes `2019…` sont-ils collés sur les produits (étiquette SPERO) ? C'est ce qui décide si 19 % des lignes et 54 % des pièces se scannent.
2. Le contrôle informe seulement (l'opérateur peut passer outre), ou il bloque la fin de préparation ?
3. OK pour une clé API dans la config TMO des postes (prod, geste d'Arnaud) ?

## 7. Limites de l'analyse

- Chiffres du labo : copie de la prod au 24/11 (synchro nocturne), pas lecture directe de la prod.
- Le rendu de la maquette utilise des pictogrammes à la place des photos produit (vraies miniatures en réel).
- Nom, tailles et codes de la maquette sont inventés ; seuls les chiffres de la section 3 sont réels.
