# Guide d'Architecture & Implémentation : Raccourci Global d'Impression d'Étiquettes

## 1. Contexte & Architecture Globale

### 1.1 Objectif
Permettre le déclenchement instantané de l'impression d'une étiquette d'expédition depuis un **mini-clavier mécanique USB (3 touches, émulation HID)** sur un poste d'emballage e-commerce.

L'impression doit fonctionner **même si l'onglet Chrome de la commande n'a pas le focus** (ex. si l'opérateur a cliqué sur une autre application ou un autre onglet).

### 1.2 Flux de travail (Workflow)
1. L'opérateur scanne le ticket de commande avec un scanner (ex. Tera).
2. Un script Python local lit le scan et ouvre automatiquement un onglet Chrome sur la page de vérification du contenu (`https://mon-ecommerce.com/admin/packing-check?order_id=XXX`).
3. L'opérateur prépare le colis.
4. L'opérateur appuie sur le bouton dédié du mini-clavier (configuré pour émettre une touche/combinaison spécifique, ex: `F12` ou `Alt+Shift+P`).
5. L'impression de l'étiquette est déclenchée sans interaction avec la souris.

### 1.3 Architecture Technique (mise à jour — implémentée dans `chrome_extension/` du dépôt TMO)

**Contrainte Chrome (MV3) qui a fait évoluer le design initial** : `chrome.commands` (seule API capable de capter une touche quand Chrome n'a pas le focus) impose une combinaison **fixe, déclarée dans `manifest.json`**, non reprogrammable par du JS — seul l'utilisateur peut la remapper via `chrome://extensions/shortcuts` (page native Chrome). Une page de réglages custom ne peut donc rendre paramétrable que le raccourci **"onglet actif"** (simple écoute `keydown`, sans restriction). Comme l'opérateur a normalement l'onglet de la commande sous les yeux au moment d'imprimer, ce canal configurable couvre l'essentiel des cas ; le canal global reste un filet de sécurité à touche fixe.

Conséquence sur l'architecture : au lieu de deux dépôts séparés, toute la logique clavier (les deux canaux) est regroupée dans **une seule extension Chrome** — celle déjà utilisée par TMO pour le nettoyage d'onglets (`chrome_extension/`). Le plugin WordPress n'a plus qu'à écouter un unique événement DOM, sans logique de raccourci :

```
+-----------------------------------------------------------------------+
|                            SYSTÈME D'EXPLOITATION                      |
|                                                                       |
|   +-----------------------+                                           |
|   | Mini-Clavier USB (HID)| --> Envoie la touche (ex: Alt+Shift+P)     |
|   +-----------------------+                   |                       |
+-----------------------------------------------|-----------------------+
                                                |
                                                v
                        +-------------------------------------------------+
                        | chrome_extension/ (dépôt TMO)                    |
                        |                                                 |
                        | background.js  : chrome.commands (hors focus,   |
                        |                   touche FIXE) → relaie un      |
                        |                   message à l'onglet commande   |
                        | content_script.js : écoute keydown (onglet      |
                        |                   FOCUS, touche PARAMÉTRABLE    |
                        |                   via options.js) + messages    |
                        |                   relayés par background.js     |
                        | options.html/.js : UI de choix du raccourci     |
                        |                   "onglet actif" (chrome.storage)|
                        +-------------------------------------------------+
                                                |
                                                v
                        window.dispatchEvent("tmo-print-request")
                                                |
                                                v
                        +-------------------------------------------------+
                        | Plugin WordPress (page de préparation commande)  |
                        | window.addEventListener("tmo-print-request", …)  |
                        | → logique métier d'impression (seule respons.)   |
                        +-------------------------------------------------+
```

---

## 2. Configuration du Matériel (Mini-Clavier USB)

* **Appareil :** Mini-clavier mécanique 3 touches avec mémoire embarquée (Onboard Memory / HID Standard).
* **Configuration initiale :** À effectuer une seule fois via le logiciel constructeur fourni.
* **Touche assignée :** Programmer la touche principale sur une combinaison rare pour éviter tout conflit avec d'autres logiciels :
  * Option recommandée : `Alt` + `Shift` + `P` (ou une touche de fonction inutilisée comme `F12`).
* **Fonctionnement :** La configuration étant stockée dans le contrôleur du clavier, aucun logiciel résident n'est requis au quotidien. Le clavier envoie un signal HID standard.

---

## 3. Extension Chrome : `chrome_extension/` (dépôt TMO)

### 3.1 Rôle & Responsabilité
L'extension gère l'intégralité de la logique clavier (les deux canaux) et n'a aucune connaissance de la logique métier d'impression : elle se contente d'émettre un événement DOM sur la page. Elle réutilise l'extension TMO existante (nettoyage des onglets `wc-better-management`) plutôt qu'un nouveau dépôt séparé.

### 3.2 Fichiers ajoutés
```
chrome_extension/
├── manifest.json      — +commande "trigger-print-global" (global, touche fixe)
│                         +content_scripts sur wp-admin/admin.php* +options_page
├── background.js       — +listener chrome.commands "trigger-print-global" → relaie
│                         un message à l'onglet wc-better-management trouvé
├── content_script.js   — écoute keydown (raccourci paramétrable) + messages relayés ;
│                         émet window.dispatchEvent("tmo-print-request")
├── options.html/.js    — UI de saisie du raccourci "onglet actif" (chrome.storage.sync,
│                         clé "tmo_print_shortcut")
```

Extrait `manifest.json` (commande globale — touche fixe, remappable uniquement via
`chrome://extensions/shortcuts`) :
```json
"trigger-print-global": {
  "suggested_key": { "default": "Alt+Shift+P" },
  "description": "Imprimer l'étiquette (raccourci global, hors focus)",
  "global": true
}
```

`background.js` relaie vers l'onglet `wc-better-management` déterminé par `findPrintTarget()` :
1. l'onglet dont l'URL porte exactement le dernier `orderCheck` (order_id) ouvert par TMO
   (mémorisé dans `chrome.storage.local` sous `tmo_last_order_id` à chaque ouverture/mise à
   jour d'un onglet TMO) ;
2. à défaut, parmi les onglets trackés par TMO (`tmo_tracked_tabs`), le plus récemment actif
   (`lastAccessed`) ;
3. à défaut, parmi tous les onglets `wc-better-management` ouverts (même non ouverts par TMO),
   le plus récemment actif.

Un simple `.find()` sur le premier onglet correspondant (ancienne implémentation) prenait
l'onglet dans l'ordre renvoyé par `chrome.tabs.query({})`, pas forcément le bon si plusieurs
onglets `wc-better-management` étaient ouverts (autre fenêtre, ancien onglet pas encore
nettoyé) — d'où l'ajout du matching par order_id et du tri par récence.
```javascript
chrome.commands.onCommand.addListener(async (cmd) => {
  if (cmd !== "trigger-print-global") return;
  const target = await findPrintTarget();
  if (!target) return;
  await chrome.tabs.sendMessage(target.id, { action: "tmo-print-request", source: "global_shortcut" });
});
```

`content_script.js` gère le canal "onglet actif" (raccourci lu depuis `chrome.storage.sync`,
réglable via `options.html`) et relaie les messages hors-focus vers le même événement DOM :
```javascript
window.addEventListener("keydown", (e) => {
  if (matchesShortcut(e)) { e.preventDefault(); dispatchPrintRequest("content_script_focused"); }
}, true);

chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (request?.action === "tmo-print-request") {
    dispatchPrintRequest(request.source || "global_shortcut");
    sendResponse({ status: "ACK" });
  }
});
```

---

## 4. Plugin WordPress : seule responsabilité restante = imprimer

Le plugin n'a plus besoin d'écouter le clavier ni les messages d'extension : il écoute
un unique événement DOM déjà dédupliqué par canal, et gère l'anti-rebond + l'appel métier.

```javascript
/**
 * Module d'impression d'étiquettes colis - Poste d'emballage
 */
(function () {
  'use strict';

  let isPrintingProcessActive = false;

  function executePrintProcess(triggerSource) {
    if (isPrintingProcessActive) {
      console.log(`[PRINT] Demande ignorée (${triggerSource}) : une impression est déjà en cours.`);
      return;
    }
    isPrintingProcessActive = true;
    console.log(`[PRINT] Déclenchement validé via : ${triggerSource}`);

    /* LOGIQUE MÉTIER D'IMPRESSION :
    const orderId = document.getElementById('order_id').value;
    fetch(`/wp-json/packing/v1/print-label/${orderId}`)
      .then(res => res.json())
      .then(data => { ... })
      .finally(() => {
        setTimeout(() => { isPrintingProcessActive = false; }, 2000);
      });
    */

    // Simulation visuelle / Log de test
    alert("Impression de l'étiquette en cours...");
    setTimeout(() => { isPrintingProcessActive = false; }, 2000);
  }

  // Unique point d'entrée : l'extension a déjà géré focus/hors-focus.
  window.addEventListener('tmo-print-request', (e) => {
    executePrintProcess(e.detail?.source || 'unknown');
  });
})();
```

---

## 5. Synthèse des Échanges

| Événement | Composant Récepteur | Statut Focus Onglet | Mode d'Interception | Raccourci |
| :--- | :--- | :--- | :--- | :--- |
| Touche pressée | **content_script.js** | **Oui (Focus)** | JavaScript `keydown` | Paramétrable (`options.html`) |
| Touche pressée | **background.js** | **Non (Hors Focus)** | API Chrome `commands` | Fixe (`chrome://extensions/shortcuts`) |
| `tmo-print-request` reçu | **Plugin WordPress** | — | `window.addEventListener` | — |

---

## 6. Anti-Rebond & Sécurité
Pour éviter qu'une pression sur la touche ne déclenche 2 impressions si l'onglet passe du statut focus à non-focus simultanément :
* Le drapeau `isPrintingProcessActive` bloque tout deuxième déclenchement survenu dans la fenêtre des 2000 ms.
* Le mécanisme garantit un comportement déterministe quel que soit l'état du navigateur.
