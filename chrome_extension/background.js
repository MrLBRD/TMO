const TARGET_PATH = "/wp-admin/admin.php";
const TARGET_PARAM = "wc-better-management";
const STORAGE_KEY = "tmo_tracked_tabs";
const LAST_ORDER_KEY = "tmo_last_order_id";
const LAST_CLEANUP_KEY = "tmo_last_cleanup";

// Sérialise les opérations qui lisent puis réécrivent chrome.storage.local
// (trackTab/untrackTab/cleanupTabs). Sans ça, deux scans rapprochés (nouvelle
// douchette rapide) déclenchent des onCreated/onUpdated quasi simultanés :
// chacun lit le même état avant que l'autre n'ait écrit, et la dernière
// écriture gagne — les entrées précédentes du tracking sont perdues.
let _storageQueue = Promise.resolve();
function serialized(fn) {
  const run = _storageQueue.then(fn, fn);
  _storageQueue = run.catch(() => {});
  return run;
}

// Vérifie si une URL est une ouverture TMO (avec orderCheck)
function isTmoOpenUrl(url) {
  try {
    const u = new URL(url);
    return u.pathname.endsWith(TARGET_PATH)
      && u.searchParams.get("page") === TARGET_PARAM
      && !!u.searchParams.get("orderCheck");
  } catch { return false; }
}

// Vérifie si une URL porte une marque d'ouverture TMO qui survit à
// l'impression : le plugin ne retire que orderCheck, pas tmoTab (ajouté par
// TMO à chaque ouverture) ni carrierCode (ajouté si le ticket le fournit —
// couvre les onglets ouverts par les versions de TMO antérieures à tmoTab).
function hasTmoMarker(url) {
  try {
    const u = new URL(url);
    return u.pathname.endsWith(TARGET_PATH)
      && u.searchParams.get("page") === TARGET_PARAM
      && (!!u.searchParams.get("orderCheck")
        || u.searchParams.get("tmoTab") === "1"
        || !!u.searchParams.get("carrierCode"));
  } catch { return false; }
}

// Vérifie si une URL est une page wc-better-management (avec ou sans orderCheck)
function isTargetPage(url) {
  try {
    const u = new URL(url);
    return u.pathname.endsWith(TARGET_PATH)
      && u.searchParams.get("page") === TARGET_PARAM;
  } catch { return false; }
}

// Extrait l'order_id (orderCheck) d'une URL, si présent
function extractOrderId(url) {
  try {
    return new URL(url).searchParams.get("orderCheck") || null;
  } catch { return null; }
}

// Ajouter un tab ID au tracking, associé à son order_id (tabId -> orderId)
async function trackTab(tabId, orderId) {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  const tracked = data[STORAGE_KEY] || {};
  tracked[tabId] = orderId;
  const toSet = { [STORAGE_KEY]: tracked };
  if (orderId) toSet[LAST_ORDER_KEY] = orderId;
  await chrome.storage.local.set(toSet);
}

// Retirer un tab ID du tracking
async function untrackTab(tabId) {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  const tracked = data[STORAGE_KEY] || {};
  if (!(tabId in tracked)) return;
  delete tracked[tabId];
  await chrome.storage.local.set({ [STORAGE_KEY]: tracked });
}

// Onglets TMO à gérer, triés du plus récent au plus ancien :
// - tout onglet dont l'URL porte une marque TMO (hasTmoMarker), même s'il n'a
//   jamais été tracké (event onCreated/onUpdated manqué, onglet restauré...) ;
// - les onglets trackés restés sur wc-better-management, même si l'URL a
//   perdu toute marque (ex. navigation entre les onglets internes du plugin).
// Tout onglet marqué est enregistré au passage dans le tracking : il reste
// ainsi reconnu plus tard, même une fois ses paramètres retirés de l'URL.
// Purge aussi du tracking les onglets qui n'existent plus.
// Note: la permission "tabs" (et non "activeTab") est requise pour lire l'URL
// de TOUS les onglets via chrome.tabs.query({}), pas seulement l'onglet actif.
async function getTmoTabs() {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  const tracked = data[STORAGE_KEY] || {};
  const allTabs = await chrome.tabs.query({});
  let dirty = false;

  const existingIds = new Set(allTabs.map(t => String(t.id)));
  for (const id of Object.keys(tracked)) {
    if (!existingIds.has(id)) { delete tracked[id]; dirty = true; }
  }

  const tabs = [];
  for (const tab of allTabs) {
    if (tab.id === undefined || tab.pinned) continue;
    if (hasTmoMarker(tab.url)) {
      if (!(tab.id in tracked)) { tracked[tab.id] = extractOrderId(tab.url); dirty = true; }
      tabs.push(tab);
    } else if (tab.id in tracked && isTargetPage(tab.url)) {
      tabs.push(tab);
    }
  }
  if (dirty) await chrome.storage.local.set({ [STORAGE_KEY]: tracked });

  // Plus récent d'abord, par tab.id : Chrome l'incrémente à chaque création
  // d'onglet, et TMO ouvre toujours un nouvel onglet. Ni lastAccessed (dépend
  // du focus) ni la date de tracking (un scan rapide peut déclencher le
  // cleanup avant que les onglets suivants soient trackés) ne sont fiables.
  return tabs.sort((a, b) => b.id - a.id);
}

// Détermine l'onglet à cibler pour l'impression hors-focus :
// 1. l'onglet dont l'URL porte exactement le dernier order_id ouvert par TMO
// 2. à défaut, parmi les onglets trackés (ouverts par TMO), le plus récemment actif
// 3. à défaut, parmi tous les onglets wc-better-management, le plus récemment actif
async function findPrintTarget() {
  const data = await chrome.storage.local.get([STORAGE_KEY, LAST_ORDER_KEY]);
  const tracked = data[STORAGE_KEY] || {};
  const lastOrderId = data[LAST_ORDER_KEY];

  const allTabs = await chrome.tabs.query({});
  const candidates = allTabs.filter(tab => tab.id !== undefined && isTargetPage(tab.url));
  if (!candidates.length) return null;

  if (lastOrderId) {
    const exact = candidates.find(tab => extractOrderId(tab.url) === lastOrderId);
    if (exact) return exact;
  }

  const trackedIds = new Set(Object.keys(tracked).map(Number));
  const trackedCandidates = candidates.filter(tab => trackedIds.has(tab.id));
  const pool = trackedCandidates.length ? trackedCandidates : candidates;

  return pool.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
}

// Cleanup : ferme tous les onglets TMO sauf le plus récent, toutes fenêtres
// confondues — Chrome ouvre l'URL dans la dernière fenêtre active, qui n'est
// pas forcément celle des onglets précédents ; un regroupement par fenêtre
// laissait un onglet par fenêtre s'accumuler. L'onglet conservé garde le
// navigateur ouvert ; une fenêtre qui ne contenait qu'un ancien onglet TMO se
// ferme avec lui.
async function cleanupTabs(reason) {
  const tabs = await getTmoTabs();
  const toClose = tabs.slice(1);
  const errors = [];

  // Un onglet à la fois : un échec (ex. "Tabs cannot be edited right now"
  // pendant un glisser d'onglet) ne doit pas empêcher de fermer les autres —
  // l'alarme périodique retentera.
  for (const tab of toClose) {
    try {
      await chrome.tabs.remove(tab.id);
      await untrackTab(tab.id);
    } catch (err) {
      errors.push(String((err && err.message) || err));
    }
  }

  // Dernier passage consultable dans la page Options (diagnostic en prod).
  const report = {
    at: Date.now(),
    reason: reason || "unknown",
    found: tabs.length,
    closed: toClose.length - errors.length,
    errors,
  };
  await chrome.storage.local.set({ [LAST_CLEANUP_KEY]: report });
  if (toClose.length || errors.length) console.info("[TMO] cleanup", report);
}

// Tracker quand une tab TMO est créée
chrome.tabs.onCreated.addListener((tab) => {
  if (tab.url && isTmoOpenUrl(tab.url)) {
    serialized(async () => {
      await trackTab(tab.id, extractOrderId(tab.url));
      await cleanupTabs("created");
    });
  }
});

// Tracker quand une tab est mise à jour avec orderCheck
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url && isTmoOpenUrl(changeInfo.url)) {
    serialized(async () => {
      await trackTab(tabId, extractOrderId(changeInfo.url));
      await cleanupTabs("updated");
    });
  } else if (changeInfo.status === "complete" && hasTmoMarker(tab.url)) {
    // Filet de sécurité : fin de chargement d'une page TMO (avant toute
    // impression). Si l'ouverture n'a pas été trackée, on la rattrape ici ;
    // cleanupTabs enregistre les onglets marqués et ferme les anciens.
    serialized(() => cleanupTabs("loaded"));
  }
});

// Nettoyer le tracking quand une tab est fermée
chrome.tabs.onRemoved.addListener((tabId) => {
  serialized(() => untrackTab(tabId));
});

// Commandes et autres triggers
chrome.commands.onCommand.addListener((cmd) => {
  if (cmd === "cleanup-tabs") serialized(() => cleanupTabs("shortcut"));
});
chrome.action.onClicked.addListener(() => serialized(() => cleanupTabs("action")));

// Raccourci global d'impression (actif même si l'onglet Woo n'a pas le focus).
// Le canal "onglet actif" (raccourci configurable) est géré directement par
// content_script.js — celui-ci ne sert que de relai pour le cas hors-focus,
// seul cas où chrome.commands (touche fixe, remappable via
// chrome://extensions/shortcuts) est nécessaire.
chrome.commands.onCommand.addListener(async (cmd) => {
  if (cmd !== "trigger-print-global") return;

  const target = await findPrintTarget();
  if (!target || target.id === undefined) {
    console.warn("[TMO] Aucun onglet commande ouvert pour l'impression.");
    return;
  }

  // Ramène l'onglet et sa fenêtre au premier plan avant d'imprimer — sans ça,
  // l'impression partirait sur un onglet resté en arrière-plan.
  try {
    await chrome.tabs.update(target.id, { active: true });
    if (target.windowId !== undefined) {
      await chrome.windows.update(target.windowId, { focused: true });
    }
  } catch (err) {
    console.warn("[TMO] Échec mise au premier plan de l'onglet :", err);
  }

  try {
    await chrome.tabs.sendMessage(target.id, {
      action: "tmo-print-request",
      source: "global_shortcut",
    });
  } catch (err) {
    console.warn("[TMO] Échec envoi message impression :", err);
  }
});

// Au démarrage de Chrome, les tab IDs repartent de zéro : le tracking de la
// session précédente ne correspond plus à rien (voire à d'autres onglets).
chrome.runtime.onStartup.addListener(() => serialized(async () => {
  await chrome.storage.local.remove(STORAGE_KEY);
  await cleanupTabs("startup");
}));
chrome.runtime.onInstalled.addListener(() => serialized(() => cleanupTabs("installed")));

// Filet de sécurité périodique (chrome.alarms : plus fiable que setInterval
// pour un service worker, qui peut être suspendu).
chrome.alarms.create("cleanup-tabs", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "cleanup-tabs") serialized(() => cleanupTabs("alarm"));
});
