// Réutilisation de l'onglet commande déjà ouvert : au lieu de charger une page
// wp-admin complète à chaque scan, on demande à la page WCBM déjà chargée
// d'ouvrir la commande (événement DOM `tmo-open-order`, voir content_script.js).
// Fichier séparé de background.js pour être testable sous Node
// (tests/extension_reuse.test.js).

const REUSE_ACK_TIMEOUT_MS = 500;

// Identifiant de commande exploitable par le contrat `tmo-open-order` (entier).
function reuseOrderId(url) {
  try {
    const raw = new URL(url).searchParams.get("orderCheck") || "";
    return /^[1-9]\d*$/.test(raw) ? Number(raw) : null;
  } catch { return null; }
}

// L'onglet existant peut-il recevoir la commande ? Même fenêtre, même site,
// page entièrement chargée et non déchargée de la mémoire par Chrome.
function canReuseTab(candidate, newTab, url) {
  if (!candidate || candidate.id === undefined || candidate.id === newTab.id) return false;
  if (candidate.windowId !== newTab.windowId) return false;
  if (candidate.status !== "complete" || candidate.discarded) return false;
  try {
    return new URL(candidate.url).origin === new URL(url).origin;
  } catch { return false; }
}

// Tente d'ouvrir la commande de `url` dans `candidate`. Renvoie true si la page
// a accepté (onglet existant activé, nouvel onglet fermé) ; false dans tous les
// autres cas, sans rien toucher : le nouvel onglet continue alors de charger
// comme avant. Un scan ne doit jamais être perdu — au moindre doute, false.
async function tryReuseTab(api, candidate, newTab, url, timeoutMs = REUSE_ACK_TIMEOUT_MS) {
  const orderId = reuseOrderId(url);
  if (orderId === null || !canReuseTab(candidate, newTab, url)) return false;

  let timer;
  let ack;
  try {
    // sendMessage rejette s'il n'y a pas de content script dans l'onglet, et
    // répond undefined si c'est une ancienne version qui ignore ce message.
    ack = await Promise.race([
      api.tabs.sendMessage(candidate.id, { action: "tmo-open-order", orderId }),
      new Promise((resolve) => { timer = setTimeout(resolve, timeoutMs); }),
    ]);
  } catch { return false; } finally { clearTimeout(timer); }
  if (!ack || ack.ok !== true || Number(ack.orderId) !== orderId) return false;

  // Si l'onglet existant ne peut pas passer au premier plan, on garde le nouveau.
  try {
    await api.tabs.update(candidate.id, { active: true });
  } catch { return false; }
  // Fermeture ratée : la commande est alors ouverte dans les deux onglets et
  // cleanupTabs garde le plus récent (le nouveau) — rien n'est perdu.
  try { await api.tabs.remove(newTab.id); } catch { /* voir ci-dessus */ }
  return true;
}

if (typeof module !== "undefined") module.exports = { reuseOrderId, canReuseTab, tryReuseTab };
