// Réutilisation de l'onglet commande (chrome_extension/reuse.js).
// Lancé par tests/test_extension_reuse.py : node --test tests/extension_reuse.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const { reuseOrderId, canReuseTab, tryReuseTab } = require("../chrome_extension/reuse.js");

const SITE = "https://univers-crampons.fr/wp-admin/admin.php?page=wc-better-management";
const URL_NEW = `${SITE}&orderCheck=4242&tmoTab=1`;
const existing = { id: 5, windowId: 1, status: "complete", discarded: false, url: `${SITE}&tmoTab=1` };
const created = { id: 9, windowId: 1 };

// Faux chrome.tabs : `reply` simule la réponse du content script.
function fakeApi(reply) {
  const calls = [];
  return {
    calls,
    tabs: {
      sendMessage: async (id, msg) => { calls.push(["send", id, msg]); return reply(msg); },
      update: async (id, props) => { calls.push(["update", id, props]); },
      remove: async (id) => { calls.push(["remove", id]); },
    },
  };
}
const touched = (api) => api.calls.filter(c => c[0] !== "send");

test("identifiant de commande : entier strict", () => {
  assert.equal(reuseOrderId(URL_NEW), 4242);
  assert.equal(reuseOrderId(`${SITE}&orderCheck=AB-12`), null);
  assert.equal(reuseOrderId(SITE), null);
});

test("candidat refusé : autre fenêtre, en chargement, déchargé, autre site, lui-même", () => {
  assert.equal(canReuseTab(existing, created, URL_NEW), true);
  assert.equal(canReuseTab(undefined, created, URL_NEW), false);
  assert.equal(canReuseTab({ ...existing, windowId: 2 }, created, URL_NEW), false);
  assert.equal(canReuseTab({ ...existing, status: "loading" }, created, URL_NEW), false);
  assert.equal(canReuseTab({ ...existing, discarded: true }, created, URL_NEW), false);
  assert.equal(canReuseTab({ ...existing, url: existing.url.replace("univers-crampons.fr", "www.univers-crampons.fr") }, created, URL_NEW), false);
  assert.equal(canReuseTab({ ...existing, id: 9 }, created, URL_NEW), false);
});

test("accepté : onglet existant activé, nouvel onglet fermé", async () => {
  const api = fakeApi((msg) => ({ orderId: msg.orderId, ok: true }));
  assert.equal(await tryReuseTab(api, existing, created, URL_NEW), true);
  assert.deepEqual(api.calls, [
    ["send", 5, { action: "tmo-open-order", orderId: 4242 }],
    ["update", 5, { active: true }],
    ["remove", 9],
  ]);
});

test("refus de la page : on ne touche à aucun onglet", async () => {
  const api = fakeApi((msg) => ({ orderId: msg.orderId, ok: false, reason: "printing" }));
  assert.equal(await tryReuseTab(api, existing, created, URL_NEW), false);
  assert.deepEqual(touched(api), []);
});

test("ancien content script (réponse vide) ou accusé d'une autre commande : nouvel onglet gardé", async () => {
  for (const reply of [() => undefined, () => ({ orderId: 1, ok: true })]) {
    const api = fakeApi(reply);
    assert.equal(await tryReuseTab(api, existing, created, URL_NEW), false);
    assert.deepEqual(touched(api), []);
  }
});

test("pas de content script (sendMessage rejette) : nouvel onglet gardé", async () => {
  const api = fakeApi(() => { throw new Error("Receiving end does not exist"); });
  assert.equal(await tryReuseTab(api, existing, created, URL_NEW), false);
  assert.deepEqual(touched(api), []);
});

test("délai dépassé : nouvel onglet gardé", async () => {
  const api = fakeApi(() => new Promise(() => {}));
  assert.equal(await tryReuseTab(api, existing, created, URL_NEW, 20), false);
  assert.deepEqual(touched(api), []);
});

test("activation impossible : nouvel onglet gardé", async () => {
  const api = fakeApi((msg) => ({ orderId: msg.orderId, ok: true }));
  api.tabs.update = async () => { throw new Error("Tabs cannot be edited right now"); };
  assert.equal(await tryReuseTab(api, existing, created, URL_NEW), false);
  assert.deepEqual(api.calls.filter(c => c[0] === "remove"), []);
});

test("candidat inutilisable : aucun message envoyé", async () => {
  const api = fakeApi(() => ({ ok: true }));
  assert.equal(await tryReuseTab(api, { ...existing, status: "loading" }, created, URL_NEW), false);
  assert.deepEqual(api.calls, []);
});
