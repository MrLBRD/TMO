// Déclenche l'impression de l'étiquette colis. Deux canaux aboutissent au même
// événement DOM, que le plugin WordPress (page de préparation de commande)
// n'a qu'à écouter une seule fois :
//
//   window.addEventListener("tmo-print-request", (e) => { ... imprimer ... });
//
// Canal 1 (onglet actif) : écoute keydown ci-dessous, raccourci entièrement
// paramétrable via la page Options de cette extension.
// Canal 2 (hors focus) : relayé par background.js via chrome.commands — touche
// fixe (contrainte Chrome), voir manifest.json.

const STORAGE_KEY = "tmo_print_shortcut";
const DEFAULT_SHORTCUT = { ctrl: false, alt: true, shift: true, meta: false, key: "p" };

let shortcut = DEFAULT_SHORTCUT;

function loadShortcut() {
  chrome.storage.sync.get(STORAGE_KEY, (data) => {
    if (data && data[STORAGE_KEY]) shortcut = data[STORAGE_KEY];
  });
}
loadShortcut();

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && changes[STORAGE_KEY]) {
    shortcut = changes[STORAGE_KEY].newValue || DEFAULT_SHORTCUT;
  }
});

function matchesShortcut(e) {
  return (
    e.ctrlKey === !!shortcut.ctrl &&
    e.altKey === !!shortcut.alt &&
    e.shiftKey === !!shortcut.shift &&
    e.metaKey === !!shortcut.meta &&
    e.key.toLowerCase() === String(shortcut.key || "").toLowerCase()
  );
}

function dispatchPrintRequest(source) {
  window.dispatchEvent(new CustomEvent("tmo-print-request", { detail: { source } }));
}

// Réutilisation de l'onglet (voir chrome_extension/reuse.js) : demande à la
// page WCBM d'ouvrir une commande sans rechargement, et renvoie sa réponse
// (`tmo-open-order-ack`) à background.js. Sans réponse à temps — ancienne
// version de WCBM sans cet écouteur — on répond ok:false : background.js garde
// alors le nouvel onglet.
const OPEN_ORDER_ACK_TIMEOUT_MS = 450; // sous les 500 ms de background.js

function relayOpenOrder(orderId, sendResponse) {
  let done = false;
  const finish = (ok, reason) => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    window.removeEventListener("tmo-open-order-ack", onAck);
    sendResponse({ orderId, ok, reason });
  };
  const onAck = (e) => {
    const d = e.detail;
    if (d && Number(d.orderId) === orderId) finish(d.ok === true, String(d.reason || ""));
  };
  window.addEventListener("tmo-open-order-ack", onAck);
  const timer = setTimeout(() => finish(false, "timeout"), OPEN_ORDER_ACK_TIMEOUT_MS);
  window.dispatchEvent(new CustomEvent("tmo-open-order", { detail: { orderId } }));
  return true; // réponse asynchrone : garde le canal sendResponse ouvert
}

window.addEventListener(
  "keydown",
  (e) => {
    if (matchesShortcut(e)) {
      e.preventDefault();
      dispatchPrintRequest("content_script_focused");
    }
  },
  true
);

chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (request && request.action === "tmo-print-request") {
    dispatchPrintRequest(request.source || "global_shortcut");
    sendResponse({ status: "ACK" });
  } else if (request && request.action === "tmo-open-order") {
    return relayOpenOrder(request.orderId, sendResponse);
  }
});
