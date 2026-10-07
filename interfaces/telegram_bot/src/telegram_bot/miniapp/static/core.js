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

export class AuthError extends Error {}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Authorization: "tma " + tg.initData };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401) throw new AuthError("expired");
  if (response.status === 403) throw new AuthError("forbidden");
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

const blobUrls = new Map();

// An authed image as an object URL (an <img src> cannot carry the Authorization header); null if missing.
export async function apiImageUrl(path) {
  if (blobUrls.has(path)) return blobUrls.get(path);
  const response = await fetch("/api" + path, { headers: { Authorization: "tma " + tg.initData } });
  if (!response.ok) return null;
  const url = URL.createObjectURL(await response.blob());
  blobUrls.set(path, url);
  return url;
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
