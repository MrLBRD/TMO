const STORAGE_KEY = "tmo_print_shortcut";
const DEFAULT_SHORTCUT = { ctrl: false, alt: true, shift: true, meta: false, key: "p" };
const IGNORED_KEYS = new Set(["Control", "Alt", "Shift", "Meta"]);
const GLOBAL_COMMAND_NAME = "trigger-print-global";
const SHORTCUTS_URL = "chrome://extensions/shortcuts";

// Alias entre KeyboardEvent.key (utilisé par content_script.js) et le
// vocabulaire de chrome.commands (utilisé par chrome://extensions/shortcuts),
// qui ne coïncident pas toujours pour les touches spéciales.
const KEY_ALIASES = {
  " ": "Space",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  ",": "Comma",
  ".": "Period",
};

function keyLabel(key) {
  if (!key) return "?";
  if (KEY_ALIASES[key]) return KEY_ALIASES[key];
  if (key.length === 1) return key.toUpperCase();
  return key; // F1..F12, Enter, Tab, etc. — déjà proches du format Chrome
}

function formatShortcutDisplay(s) {
  const parts = [];
  if (s.ctrl) parts.push("Ctrl");
  if (s.alt) parts.push("Alt");
  if (s.shift) parts.push("Shift");
  if (s.meta) parts.push("Meta");
  parts.push(keyLabel(s.key));
  return parts.join(" + ");
}

function parseChromeShortcutString(str) {
  if (!str) return null;
  const tokens = str.split("+").map((t) => t.trim());
  const key = tokens[tokens.length - 1];
  const mods = new Set(tokens.slice(0, -1));
  return {
    ctrl: mods.has("Ctrl") || mods.has("Control"),
    alt: mods.has("Alt"),
    shift: mods.has("Shift"),
    meta: mods.has("Command") || mods.has("Meta"),
    key,
  };
}

function shortcutsMatch(a, b) {
  if (!a || !b) return false;
  return (
    !!a.ctrl === !!b.ctrl &&
    !!a.alt === !!b.alt &&
    !!a.shift === !!b.shift &&
    !!a.meta === !!b.meta &&
    keyLabel(a.key).toLowerCase() === keyLabel(b.key).toLowerCase()
  );
}

const comboEl = document.getElementById("combo");
const statusEl = document.getElementById("status");
const globalCheckEl = document.getElementById("global-check");
const refreshBtn = document.getElementById("refresh-global");

function loadShortcut() {
  chrome.storage.sync.get(STORAGE_KEY, (data) => {
    const s = (data && data[STORAGE_KEY]) || DEFAULT_SHORTCUT;
    comboEl.textContent = formatShortcutDisplay(s);
  });
}
loadShortcut();

comboEl.addEventListener("click", () => {
  comboEl.classList.add("recording");
  comboEl.textContent = "Appuyez sur une touche...";
});

comboEl.addEventListener("keydown", (e) => {
  if (!comboEl.classList.contains("recording")) return;
  e.preventDefault();
  if (IGNORED_KEYS.has(e.key)) return;

  const shortcut = {
    ctrl: e.ctrlKey,
    alt: e.altKey,
    shift: e.shiftKey,
    meta: e.metaKey,
    key: e.key,
  };

  chrome.storage.sync.set({ [STORAGE_KEY]: shortcut }, () => {
    comboEl.classList.remove("recording");
    comboEl.textContent = formatShortcutDisplay(shortcut);
    statusEl.textContent = "Raccourci enregistré.";
    setTimeout(() => {
      statusEl.textContent = "";
    }, 2000);
    checkGlobalShortcut();
  });
});

comboEl.addEventListener("blur", () => {
  if (comboEl.classList.contains("recording")) {
    comboEl.classList.remove("recording");
    loadShortcut();
  }
});

// Chrome ne fournit AUCUNE API pour définir/modifier une touche de
// chrome.commands depuis le JS (seulement getAll() en lecture) — le raccourci
// global reste réglable uniquement à la main, par l'utilisateur, sur
// chrome://extensions/shortcuts. On se contente donc de détecter un écart
// avec le raccourci "onglet actif" ci-dessus et de faciliter la correction.
function appendOpenShortcutsButton(container, targetLabel) {
  const btn = document.createElement("button");
  btn.textContent = `Ouvrir chrome://extensions/shortcuts (régler sur ${targetLabel})`;
  btn.addEventListener("click", () => {
    chrome.tabs.create({ url: SHORTCUTS_URL }).catch(() => {
      // Si la navigation programmatique est bloquée par cette version de
      // Chrome, l'URL reste affichée juste en dessous pour copier/coller.
    });
  });

  const urlLine = document.createElement("div");
  urlLine.style.marginTop = "6px";
  urlLine.style.fontFamily = "monospace";
  urlLine.style.fontSize = "11px";
  urlLine.style.userSelect = "all";
  urlLine.textContent = SHORTCUTS_URL;

  container.appendChild(document.createElement("br"));
  container.appendChild(btn);
  container.appendChild(urlLine);
}

function checkGlobalShortcut() {
  chrome.storage.sync.get(STORAGE_KEY, (data) => {
    const focused = (data && data[STORAGE_KEY]) || DEFAULT_SHORTCUT;
    const focusedLabel = formatShortcutDisplay(focused);

    chrome.commands.getAll((commands) => {
      const globalCmd = (commands || []).find((c) => c.name === GLOBAL_COMMAND_NAME);
      const globalShortcut = globalCmd ? parseChromeShortcutString(globalCmd.shortcut) : null;

      globalCheckEl.textContent = "";
      globalCheckEl.className = "";

      if (!globalShortcut) {
        globalCheckEl.className = "diverges";
        globalCheckEl.appendChild(
          document.createTextNode(
            "Aucun raccourci global n'est assigné dans Chrome — le déclenchement hors focus ne fonctionnera pas tant qu'il n'est pas réglé."
          )
        );
        appendOpenShortcutsButton(globalCheckEl, focusedLabel);
        return;
      }

      if (shortcutsMatch(focused, globalShortcut)) {
        globalCheckEl.className = "ok";
        globalCheckEl.textContent = `Raccourci global aligné : ${formatShortcutDisplay(globalShortcut)}.`;
      } else {
        globalCheckEl.className = "diverges";
        globalCheckEl.appendChild(
          document.createTextNode(
            `Le raccourci global actuel (${formatShortcutDisplay(globalShortcut)}) diffère du raccourci ` +
              `"onglet actif" (${focusedLabel}). Chrome ne permet pas de le synchroniser automatiquement.`
          )
        );
        appendOpenShortcutsButton(globalCheckEl, focusedLabel);
      }
    });
  });
}

checkGlobalShortcut();
refreshBtn.addEventListener("click", checkGlobalShortcut);
// Revérifie automatiquement au retour sur cet onglet (ex. après avoir remappé
// la touche dans l'onglet chrome://extensions/shortcuts ouvert à côté).
window.addEventListener("focus", checkGlobalShortcut);
