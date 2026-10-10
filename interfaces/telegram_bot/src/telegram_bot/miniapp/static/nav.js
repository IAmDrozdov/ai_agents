// The top bar («◧ Место · режим ▾ … действия») and the popup menu every list and screen shares (ADR-021).

import { el, haptic } from "./core.js";

const EDGE = 8; // a menu keeps this far from the window's edges
const GAP = 4; // between an anchor and its menu

let closeOpen = null; // closes the menu on screen

export function closeMenu() {
  closeOpen?.();
}

function itemNode(item, close) {
  if (item.sep) return el("div", "menu-sep");
  if (item.node) return item.node;
  const button = el("button", ["menu-item", item.tone, item.on && "on", item.dim && "dim"].filter(Boolean).join(" "));
  button.type = "button";
  button.setAttribute("role", "menuitem");
  if (item.color) button.style.setProperty("--chip", item.color);
  if (item.icon != null) button.append(el("span", "ic", item.icon));
  button.append(el("span", "lb", item.label));
  if (item.note != null) button.append(el("span", "n", String(item.note)));
  button.onclick = () => {
    close();
    item.run();
  };
  return button;
}

// Shows a menu under `anchor`, or with its corner at opts.at = { x, y } (window coordinates). items:
// { label, run, icon, note, tone: "good" | "danger", on, dim, color } | { sep: true } | { node } (a ready row).
// A click outside or Esc closes it; the anchor carries the class `open` meanwhile.
export function openMenu(anchor, items, { align = "left", at = null } = {}) {
  closeMenu();
  const menu = document.getElementById("menu");
  const veil = el("div", "menu-veil");

  function close() {
    if (closeOpen !== close) return;
    closeOpen = null;
    document.removeEventListener("keydown", onKey, true);
    veil.remove();
    menu.hidden = true;
    menu.replaceChildren();
    anchor?.classList.remove("open");
  }
  function onKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation(); // this Esc closed the menu; it does not also leave Search
    close();
  }
  veil.onclick = close;
  veil.oncontextmenu = (event) => {
    event.preventDefault();
    close();
  };

  menu.setAttribute("role", "menu");
  menu.replaceChildren(...items.map((item) => itemNode(item, close)));
  menu.style.maxHeight = `${window.innerHeight - 2 * EDGE}px`;
  menu.style.left = "0";
  menu.style.top = "0";
  menu.hidden = false;
  menu.before(veil);

  const width = menu.offsetWidth;
  const height = menu.offsetHeight;
  const rect = anchor?.getBoundingClientRect();
  let x = at ? at.x : align === "right" ? rect.right - width : rect.left;
  let y = at ? at.y : rect.bottom + GAP;
  x = Math.max(EDGE, Math.min(x, document.documentElement.clientWidth - width - EDGE));
  if (y + height > window.innerHeight - EDGE) y = Math.max(EDGE, window.innerHeight - EDGE - height);
  // In page coordinates: the menu scrolls with what it belongs to.
  menu.style.left = `${x + window.scrollX}px`;
  menu.style.top = `${y + window.scrollY}px`;

  anchor?.classList.add("open");
  document.addEventListener("keydown", onKey, true);
  closeOpen = close;
  if (at) haptic("select");
}

// places: [{ id, label }]; modes: [{ id, label, word }] (`word` follows the place's name on the button);
// remembered(placeId) is the mode a tap on the place's name opens; go(placeId, modeId) and usage() run from the menu.
// Returns { set({ place, mode, left, right, replace }) }: `left` and `right` are the view's own action nodes,
// `replace` a row of nodes shown instead of the whole bar (Search, Section edit mode).
export function mountTopbar(root, { places, modes, remembered, go, usage }) {
  const placeButton = el("button", "place");
  const name = el("span");
  const mode = el("span", "mode");
  placeButton.append(name, mode, el("span", "caret"));
  placeButton.setAttribute("aria-haspopup", "menu");
  const right = el("div", "right");
  let current = null; // the place whose row is marked in the menu

  function placeRow(place) {
    const row = el("div", "place-row" + (place.id === current ? " on" : ""));
    const open = el("button", "name", place.label);
    open.onclick = () => {
      closeMenu();
      go(place.id, remembered(place.id));
    };
    const seg = el("div", "seg2");
    for (const m of modes) {
      const button = el("button", m.id === remembered(place.id) ? "on" : null, m.label);
      button.onclick = () => {
        closeMenu();
        go(place.id, m.id);
      };
      seg.append(button);
    }
    row.append(open, seg);
    return row;
  }

  placeButton.onclick = () =>
    openMenu(placeButton, [
      ...places.map((place) => ({ node: placeRow(place) })),
      { sep: true },
      { icon: "⚙️", label: "Расходы", run: usage },
    ]);

  function set({ place, mode: modeId, left = [], right: actions = [], replace = null }) {
    current = place;
    name.textContent = places.find((p) => p.id === place).label;
    mode.textContent = "· " + modes.find((m) => m.id === modeId).word;
    right.replaceChildren(...actions);
    root.replaceChildren(...(replace ?? [...left, placeButton, right]));
  }

  return { set };
}
