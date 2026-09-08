const TARGET_PATH = "/wp-admin/admin.php";
const TARGET_PARAM = "wc-better-management";
const STORAGE_KEY = "tmo_tracked_tabs";
const LAST_ORDER_KEY = "tmo_last_order_id";

// Sérialise les opérations qui lisent puis réécrivent chrome.storage.local
// (trackTab/untrackTab/cleanupTabs). Sans ça, deux scans rapprochés (nouvelle
// douchette rapide) déclenchent des onCreated/onUpdated quasi simultanés :
// chacun lit le même état avant que l'autre n'ait écrit, et la dernière
// écriture gagne — les entrées précédentes du tracking sont perdues et
// cleanupTabs ne voit alors plus assez d'onglets trackés pour fermer les
// anciens.
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
  delete tracked[tabId];
  await chrome.storage.local.set({ [STORAGE_KEY]: tracked });
}

// Récupérer les tabs TMO trackées
async function getTrackedTabs() {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  const trackedIds = new Set(Object.keys(data[STORAGE_KEY] || {}).map(Number));
  if (!trackedIds.size) return [];

  const allTabs = await chrome.tabs.query({});
  return allTabs.filter(tab =>
    trackedIds.has(tab.id) && isTargetPage(tab.url)
  );
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

// Cleanup: ferme les anciennes tabs TMO, garde la plus récente
async function cleanupTabs() {
  const targets = await getTrackedTabs();
  if (targets.length <= 1) return;

  // Grouper par window
  const byWindow = new Map();
  for (const tab of targets) {
    if (!byWindow.has(tab.windowId)) byWindow.set(tab.windowId, []);
    byWindow.get(tab.windowId).push(tab);
  }

  for (const tabs of byWindow.values()) {
    if (tabs.length <= 1) continue;

    // Trier par lastAccessed desc, garder le premier
    const sorted = tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
    const toClose = sorted.slice(1).map(t => t.id).filter(id => id !== undefined);

    if (!toClose.length) continue;

    // Vérifier qu'on ne ferme pas le dernier tab de la window
    const windowTabs = await chrome.tabs.query({ windowId: sorted[0].windowId });
    if (windowTabs.length <= toClose.length) continue;

    await chrome.tabs.remove(toClose);
    // Retirer du tracking
    for (const id of toClose) await untrackTab(id);
  }
}

// Tracker quand une tab TMO est créée
// Note: la permission "tabs" (et non "activeTab") est requise car getTrackedTabs()
// appelle chrome.tabs.query({}) pour retrouver TOUTES les tabs trackées, pas seulement
// la tab active. L'extension doit fermer les anciennes tabs, pas la tab courante.
chrome.tabs.onCreated.addListener((tab) => {
  if (tab.url && isTmoOpenUrl(tab.url)) {
    serialized(async () => {
      await trackTab(tab.id, extractOrderId(tab.url));
      await cleanupTabs();
    });
  }
});

// Tracker quand une tab est mise à jour avec orderCheck
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url && isTmoOpenUrl(changeInfo.url)) {
    serialized(async () => {
      await trackTab(tabId, extractOrderId(changeInfo.url));
      await cleanupTabs();
    });
  }
});

// Nettoyer le tracking quand une tab est fermée
chrome.tabs.onRemoved.addListener((tabId) => {
  serialized(() => untrackTab(tabId));
});

// Commandes et autres triggers
chrome.commands.onCommand.addListener((cmd) => {
  if (cmd === "cleanup-tabs") serialized(() => cleanupTabs());
});
chrome.action.onClicked.addListener(() => serialized(() => cleanupTabs()));

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
chrome.runtime.onStartup.addListener(() => serialized(() => cleanupTabs()));
chrome.runtime.onInstalled.addListener(() => serialized(() => cleanupTabs()));

// Periodic cleanup avec chrome.alarms (plus fiable que setInterval pour service workers)
chrome.alarms.create("cleanup-tabs", { periodInMinutes: 10 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "cleanup-tabs") serialized(() => cleanupTabs());
});
