// Shared helpers: Telegram bridge, signed API calls and DOM building. Data always goes through textContent.

export const tg = window.Telegram?.WebApp ?? null;

export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

export function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

// Makes parent's children exactly `nodes`, touching only what differs, so kept nodes (and their images) stay put.
export function reconcile(parent, nodes) {
  const wanted = new Set(nodes);
  let cursor = parent.firstChild;
  for (const node of nodes) {
    while (cursor && cursor !== node && !wanted.has(cursor)) {
      const stale = cursor;
      cursor = cursor.nextSibling;
      stale.remove();
    }
    if (cursor === node) cursor = cursor.nextSibling;
    else parent.insertBefore(node, cursor);
  }
  while (cursor) {
    const next = cursor.nextSibling;
    cursor.remove();
    cursor = next;
  }
}

// Rebuilds node's children only when `key` differs from the last call.
export function slot(node, key, build) {
  if (node.dataset.key === key) return;
  node.dataset.key = key;
  node.replaceChildren(...build());
}

// Makes the next slot() call on node rebuild whatever its key.
export function resetSlot(node) {
  delete node.dataset.key;
}

export class AuthError extends Error {}

// --- snapshots: the last answers, kept across launches so a view paints before the network answers (ADR-019) ---

const SNAPSHOT_KEY = "snapshot_v1";
const SNAPSHOT_ENTRIES = 40;
const SNAPSHOT_CHARS = 900_000; // DeviceStorage holds 5 MB per user
const SNAPSHOT_READ_MS = 500;
const snapshots = new Map(); // key -> data, the most recent last
let persistTimer = 0;
let wiped = false; // a 401 or 403 cleared them: nothing writes them again during this launch

// DeviceStorage persists on the phones (Bot API 9.0); localStorage does not on some webviews. A client may still
// answer DeviceStorage with an error (Telegram Web: UNSUPPORTED), and then this launch uses localStorage.
let deviceStorageFailed = false;
const deviceStorage = () => (!deviceStorageFailed && atLeast("9.0") && tg.DeviceStorage) || null;
const localKey = () => `${SNAPSHOT_KEY}_${tg.initDataUnsafe?.user?.id ?? "anon"}`;

function readLocal() {
  try {
    return localStorage.getItem(localKey());
  } catch {
    return null;
  }
}

function readSnapshots() {
  const store = deviceStorage();
  if (!store) return Promise.resolve(readLocal());
  return new Promise((resolve) => {
    const fallBack = () => {
      deviceStorageFailed = true;
      resolve(readLocal());
    };
    const timer = setTimeout(() => resolve(null), SNAPSHOT_READ_MS); // slow, not broken: keep DeviceStorage
    try {
      store.getItem(SNAPSHOT_KEY, (error, value) => {
        clearTimeout(timer);
        if (error) fallBack();
        else resolve(value);
      });
    } catch {
      clearTimeout(timer);
      fallBack();
    }
  });
}

function writeLocal(raw) {
  try {
    if (raw == null) localStorage.removeItem(localKey());
    else localStorage.setItem(localKey(), raw);
  } catch {
    // full or blocked storage: the app works without snapshots
  }
}

function writeSnapshots(raw) {
  const store = deviceStorage();
  if (!store) {
    writeLocal(raw);
    return;
  }
  const done = (error) => {
    if (!error) return;
    deviceStorageFailed = true;
    writeLocal(raw);
  };
  try {
    if (raw == null) store.removeItem(SNAPSHOT_KEY, done);
    else store.setItem(SNAPSHOT_KEY, raw, done);
  } catch {
    done(true);
  }
}

// Reads what the last launch kept; never throws and never waits longer than SNAPSHOT_READ_MS.
export async function loadSnapshots() {
  const raw = await readSnapshots();
  try {
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed?.v === 1 && Array.isArray(parsed.entries)) {
      for (const [key, data] of parsed.entries) snapshots.set(key, data);
    }
  } catch {
    // a damaged snapshot is no snapshot
  }
}

export const snapshot = (key) => snapshots.get(key) ?? null;

export function keepSnapshot(key, data) {
  if (wiped) return;
  snapshots.delete(key);
  snapshots.set(key, data);
  while (snapshots.size > SNAPSHOT_ENTRIES) snapshots.delete(snapshots.keys().next().value);
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    let entries = [...snapshots];
    let raw = JSON.stringify({ v: 1, entries });
    while (raw.length > SNAPSHOT_CHARS && entries.length > 1) {
      entries = entries.slice(1);
      raw = JSON.stringify({ v: 1, entries });
    }
    writeSnapshots(raw);
  }, 300);
}

function forgetSnapshots() {
  wiped = true;
  snapshots.clear();
  clearTimeout(persistTimer);
  writeSnapshots(null);
  writeLocal(null); // a launch that fell back may have left a copy here too
}

// The pause before asking again about Items still being enriched: quick at first, then every 30 s,
// but never before the earliest scheduled Enrichment retry is due.
const POLL_STEPS_MS = [3000, 5000, 10000, 20000, 30000];
const RETRY_SLACK_MS = 5000; // after a scheduled Enrichment retry, before asking how it went
export function pollDelay(step, pending) {
  const delay = POLL_STEPS_MS[Math.min(step, POLL_STEPS_MS.length - 1)];
  const retry = Math.min(...pending.map((item) => parseTs(item.next_enrich_at)?.getTime() ?? 0));
  return retry - Date.now() > delay ? Math.min(retry - Date.now() + RETRY_SLACK_MS, 2 ** 31 - 1) : delay;
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Authorization: "tma " + tg.initData };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 || response.status === 403) {
    forgetSnapshots(); // nothing of the Owner's stays on a device that lost access
    throw new AuthError(response.status === 401 ? "expired" : "forbidden");
  }
  if (!response.ok) {
    let detail = response.status === 422 ? "Проверь введённые данные" : "Ошибка " + response.status;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      // the body was not JSON: keep the status text
    }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

const images = new Map(); // path -> Promise of an object URL, shared by every card asking for it

// An authed image as an object URL (an <img src> cannot carry the Authorization header); null if missing.
export function apiImageUrl(path) {
  if (!images.has(path)) {
    const load = fetch("/api" + path, { headers: { Authorization: "tma " + tg.initData } })
      .then(async (response) => (response.ok ? URL.createObjectURL(await response.blob()) : null))
      .catch(() => null);
    images.set(path, load);
    load.then((url) => url || images.delete(path)); // a failed one is asked for again next time
  }
  return images.get(path);
}

let toastTimer = null;
export function toast(text) {
  const box = document.getElementById("toast");
  box.textContent = text;
  box.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove("show"), 2600);
}

let halted = false;
export const isHalted = () => halted;

// Replaces the whole app with a message; a view that finishes loading afterwards must not paint over it.
export function showMessage(text) {
  halted = true;
  document.getElementById("tabs").replaceChildren();
  document.getElementById("view").replaceChildren(el("p", "message", text));
}

export function handleError(error) {
  if (error instanceof AuthError) {
    showMessage(
      error.message === "forbidden"
        ? "Нет доступа."
        : "Сессия устарела — закрой приложение и открой снова.",
    );
  } else if (error instanceof TypeError) {
    toast("Нет связи с сервером"); // fetch rejects with a TypeError when the network is down
  } else {
    toast(error.message || "Что-то пошло не так");
  }
}

// Runs fn; on failure shows the error and resolves undefined.
export async function attempt(fn) {
  try {
    return await fn();
  } catch (error) {
    handleError(error);
    return undefined;
  }
}

export function openUrl(url) {
  if (!/^https?:\/\//i.test(url)) return;
  if (/^https?:\/\/t\.me\//i.test(url) && tg.openTelegramLink) tg.openTelegramLink(url);
  else tg.openLink(url);
}

const atLeast = (version) => Boolean(tg?.isVersionAtLeast?.(version));

// Full height, no swipe-down-to-minimise (a scroll at the top would drag the whole sheet), page-coloured backdrop.
export function prepareShell() {
  tg.ready();
  tg.expand();
  try {
    if (atLeast("7.7")) tg.disableVerticalSwipes();
    if (atLeast("6.1")) tg.setBackgroundColor("secondary_bg_color");
  } catch {
    // cosmetic only: a client that rejects these still gets a working app
  }
}

let backHandler = null;
export function setBack(handler) {
  if (!atLeast("6.1")) return;
  if (backHandler) tg.BackButton.offClick(backHandler);
  backHandler = handler;
  if (handler) {
    tg.BackButton.onClick(handler);
    tg.BackButton.show();
  } else {
    tg.BackButton.hide();
  }
}

export function confirmAction(message) {
  if (!atLeast("6.2")) return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => tg.showConfirm(message, resolve));
}

export function haptic(kind) {
  if (!atLeast("6.1")) return;
  if (kind === "select") tg.HapticFeedback.selectionChanged();
  else tg.HapticFeedback.notificationOccurred(kind);
}

// Russian plural form for n: plural(2, "запись", "записи", "записей").
export function plural(n, one, few, many) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

// Timestamps from the database are UTC "YYYY-MM-DD HH:MM:SS"; a Due arrives as ISO UTC.
export function parseTs(ts) {
  if (!ts) return null;
  return new Date(ts.includes("T") ? ts : ts.replace(" ", "T") + "Z");
}
