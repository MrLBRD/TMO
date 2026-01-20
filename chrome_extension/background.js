const TARGET_PATH = "/wp-admin/admin.php";
const TARGET_PARAM = "wc-better-management";
const STORAGE_KEY = "tmo_tracked_tabs";

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

// Ajouter un tab ID au tracking
async function trackTab(tabId) {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  const tracked = new Set(data[STORAGE_KEY] || []);
  tracked.add(tabId);
  await chrome.storage.local.set({ [STORAGE_KEY]: [...tracked] });
}

// Retirer un tab ID du tracking
async function untrackTab(tabId) {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  const tracked = new Set(data[STORAGE_KEY] || []);
  tracked.delete(tabId);
  await chrome.storage.local.set({ [STORAGE_KEY]: [...tracked] });
}

// Récupérer les tabs TMO trackées
async function getTrackedTabs() {
  const data = await chrome.storage.local.get(STORAGE_KEY);
  const trackedIds = new Set(data[STORAGE_KEY] || []);
  if (!trackedIds.size) return [];

  const allTabs = await chrome.tabs.query({});
  return allTabs.filter(tab =>
    trackedIds.has(tab.id) && isTargetPage(tab.url)
  );
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
chrome.tabs.onCreated.addListener((tab) => {
  if (tab.url && isTmoOpenUrl(tab.url)) {
    trackTab(tab.id);
    setTimeout(cleanupTabs, 800);
  }
});

// Tracker quand une tab est mise à jour avec orderCheck
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url && isTmoOpenUrl(changeInfo.url)) {
    trackTab(tabId);
    setTimeout(cleanupTabs, 800);
  }
});

// Nettoyer le tracking quand une tab est fermée
chrome.tabs.onRemoved.addListener((tabId) => {
  untrackTab(tabId);
});

// Commandes et autres triggers
chrome.commands.onCommand.addListener((cmd) => {
  if (cmd === "cleanup-tabs") cleanupTabs();
});
chrome.action.onClicked.addListener(() => cleanupTabs());
chrome.runtime.onStartup.addListener(() => cleanupTabs());
chrome.runtime.onInstalled.addListener(() => cleanupTabs());

// Periodic cleanup avec chrome.alarms (plus fiable que setInterval pour service workers)
chrome.alarms.create("cleanup-tabs", { periodInMinutes: 10 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "cleanup-tabs") cleanupTabs();
});
