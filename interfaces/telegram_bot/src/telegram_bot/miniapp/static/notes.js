// Заметки: Section chips, the Status switch, the item list and the item view.
// Nothing is rebuilt on a tap: controls are built once and only change class or text, cards are reused by id.

import {
  AuthError,
  api,
  apiImageUrl,
  attempt,
  confirmAction,
  el,
  handleError,
  haptic,
  openUrl,
  parseTs,
  reconcile,
  setBack,
  setText,
  slot,
  tg,
  toast,
} from "./core.js";

const PAGE = 50;
const MAX_CHUNK = 100; // the most items the server returns in one request
const STATUSES = [
  ["todo", "Сделать"],
  ["done", "Готово"],
];
const OTHER = "other";
const STALE_AFTER_MS = 350;
// The item fields the top of the item view shows; it is rebuilt only when one of them changes.
const HEAD_FIELDS = [
  "kind", "url", "title", "text", "source", "author", "gist", "file_name",
  "created_at", "enrichment_status", "enrichment_error", "caption",
  "transcript", "sender", "duration_s", "tg_message_id",
]; // prettier-ignore

const isHttp = (url) => /^https?:\/\//i.test(url || "");
const itemTitle = (item) =>
  item.title || item.url || item.file_name || item.text || (item.kind === "voice" ? "🎤 Голосовое" : "Без названия");
const originOf = (item) =>
  [item.source, item.author, item.sender && "↪️ " + item.sender].filter(Boolean).join(" · ");
const hasPreview = (item) =>
  item.kind === "file" || (item.kind === "voice" && (item.file_mime || "").startsWith("video/"));

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function fmtDate(ts) {
  const date = parseTs(ts);
  return date ? date.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" }) : "—";
}

function sectionChip(section) {
  const chip = el("span", "chip", `${section.emoji} ${section.name}`.trim());
  chip.style.setProperty("--chip", section.color);
  return chip;
}

function externalLink(item, title) {
  const link = el("a", "title", title);
  link.href = item.url;
  link.onclick = (event) => {
    event.preventDefault();
    event.stopPropagation();
    openUrl(item.url);
  };
  return link;
}

function enrichmentBadge(item) {
  if (item.enrichment_status === "pending") return el("div", "badge run", "⏳ разбираю");
  const why = item.enrichment_error ? ": " + item.enrichment_error : "";
  return el("div", "badge err", "⚠️ не разобрано" + why);
}

// handlers: open(item) shows the item view, changed(item) receives an item the card re-enriched.
function card(item, handlers) {
  const node = el("article", "card clickable");
  node.onclick = () => handlers.open(item);
  if (isHttp(item.image_url)) {
    const img = el("img", "thumb");
    img.alt = "";
    img.loading = "lazy";
    img.referrerPolicy = "no-referrer";
    img.src = item.image_url;
    node.append(img);
  } else if (hasPreview(item)) {
    const img = el("img", "thumb");
    img.alt = "";
    node.append(img);
    apiImageUrl(`/notes/items/${item.id}/preview`).then((url) => {
      if (url) img.src = url;
      else img.remove();
    });
  }

  const body = el("div", "card-body");
  const title = itemTitle(item);
  if (item.kind === "link" && isHttp(item.url)) body.append(externalLink(item, title));
  else body.append(el("div", "title", title));
  const origin = originOf(item);
  if (origin) body.append(el("div", "origin", origin));
  if (item.kind === "file" && item.file_name) body.append(el("div", "origin", "📎 " + item.file_name));
  if (item.kind === "voice") body.append(el("div", "origin", "🎤 " + fmtDuration(item.duration_s)));
  if (item.gist) body.append(el("div", "gist", item.gist));
  if (item.kind !== "note" && item.text) body.append(el("div", "annotation", "✍️ " + item.text));

  const meta = el("div", "meta");
  for (const section of item.sections) meta.append(sectionChip(section));
  body.append(meta);

  if (item.enrichment_status === "pending") {
    body.append(enrichmentBadge(item));
  } else if (item.enrichment_status === "failed") {
    body.append(enrichmentBadge(item));
    const retry = el("button", "btn small", "Разобрать заново");
    retry.onclick = async (event) => {
      event.stopPropagation();
      const updated = await attempt(() => api(`/notes/items/${item.id}/reenrich`, { method: "POST" }));
      if (updated) handlers.changed(updated);
    };
    body.append(retry);
  }
  node.append(body);
  return node;
}

// launch.itemId opens that item straight away (the ✏️ Открыть button in the chat).
export async function mountNotes(root, launch = {}) {
  setBack(null);
  const state = {
    sections: [],
    selected: new Set(),
    status: "todo",
    items: [],
    total: 0,
    ticket: 0,
    loading: false,
    failed: false,
    detail: null,
    version: 0, // bumps whenever the open item changes hands, so a late reply cannot land on another item
    rev: 0, // bumps when the Owner starts a change, so an older copy fetched in the background is dropped
    dirty: false,
    busy: false,
    draft: null, // unsaved text of the open item
    listScroll: 0,
  };
  const listView = el("div");
  const detailView = el("div");
  detailView.hidden = true;
  root.replaceChildren(listView, detailView);

  const chips = el("div", "chips");
  const switcher = el("div", "segmented");
  const list = el("div", "cards");
  const more = el("button", "btn wide", "Показать ещё");
  listView.append(chips, switcher, list, more);

  // --- Status switch and chips ---------------------------------------------

  function filterQuery() {
    const query = new URLSearchParams({ status: state.status });
    for (const slug of state.selected) query.append("section", slug);
    return query;
  }

  const allChip = el("button", "chip filter", "Все");
  allChip.onclick = () => {
    state.selected.clear();
    syncChips();
    load(true);
  };
  chips.append(allChip);
  const chipButtons = new Map(); // slug -> button
  let chipsKey = "";

  function syncChips() {
    const key = state.sections.map((s) => `${s.slug}|${s.emoji}|${s.name}|${s.color}`).join("\n");
    if (key !== chipsKey) {
      chipsKey = key;
      const left = chips.scrollLeft;
      chipButtons.clear();
      chips.replaceChildren(allChip);
      for (const section of state.sections) {
        const button = el("button", "chip filter");
        button.style.setProperty("--chip", section.color);
        button.onclick = () => {
          if (!state.selected.delete(section.slug)) state.selected.add(section.slug);
          syncChips();
          load(true);
        };
        chipButtons.set(section.slug, button);
        chips.append(button);
      }
      chips.scrollLeft = left;
    }
    allChip.classList.toggle("on", state.selected.size === 0);
    for (const section of state.sections) {
      const button = chipButtons.get(section.slug);
      const count = state.status === "todo" ? ` · ${section.todo_count}` : "";
      button.classList.toggle("on", state.selected.has(section.slug));
      setText(button, `${section.emoji} ${section.name}${count}`);
    }
  }

  const statusTabs = new Map();
  for (const [value, label] of STATUSES) {
    const button = el("button", "seg", label);
    button.onclick = () => {
      if (state.status === value) return;
      state.status = value;
      syncControls();
      load(true);
    };
    statusTabs.set(value, button);
    switcher.append(button);
  }

  function syncControls() {
    for (const [value, button] of statusTabs) button.classList.toggle("on", state.status === value);
    syncChips();
  }

  // --- list ----------------------------------------------------------------

  const cardCache = new Map(); // id -> { sig, node }
  const note = el("p", "empty");

  function cardFor(item) {
    const sig = JSON.stringify(item);
    const hit = cardCache.get(item.id);
    if (hit && hit.sig === sig) return hit.node;
    const node = card(item, { open: openItem, changed: replaceItem });
    cardCache.set(item.id, { sig, node });
    return node;
  }

  function emptyText() {
    if (state.loading) return "Загрузка…";
    if (state.failed) return "Не удалось загрузить список.";
    if (state.selected.size) return "Под фильтр ничего не попало.";
    return state.status === "todo" ? "Пока пусто. Кинь боту ссылку или заметку." : "Тут пусто.";
  }

  function renderList() {
    const live = new Set(state.items.map((item) => item.id));
    for (const id of cardCache.keys()) if (!live.has(id)) cardCache.delete(id);
    let nodes = state.items.map(cardFor);
    if (!nodes.length) {
      setText(note, emptyText());
      nodes = [note];
    }
    reconcile(list, nodes);
    more.hidden = !state.failed && state.items.length >= state.total;
    more.disabled = state.loading;
    setText(more, state.failed ? "Повторить" : "Показать ещё");
  }

  // `want` items from `offset`, in requests the server accepts, all under the filter as it is now.
  async function fetchItems(offset, want) {
    const base = filterQuery().toString();
    const items = [];
    for (;;) {
      const query = new URLSearchParams(base);
      query.set("offset", String(offset + items.length));
      query.set("limit", String(Math.min(MAX_CHUNK, want - items.length)));
      const data = await api("/notes/items?" + query);
      items.push(...data.items);
      if (!data.items.length || items.length >= want || offset + items.length >= data.total) {
        return { items, total: data.total };
      }
    }
  }

  // A reset keeps the old list on screen until the new one arrives, then swaps it once.
  // `want` is how many items a reset brings back; `soft` keeps the list if the request fails.
  async function load(reset, want = PAGE, soft = false) {
    if (!reset && state.loading) return;
    const ticket = ++state.ticket;
    state.loading = true;
    more.disabled = true;
    const dim = () => {
      if (ticket === state.ticket) list.classList.add("stale");
    };
    const staleTimer = reset && state.items.length ? setTimeout(dim, STALE_AFTER_MS) : null;
    const data = await attempt(() => fetchItems(reset ? 0 : state.items.length, want));
    clearTimeout(staleTimer);
    if (ticket !== state.ticket) return;
    list.classList.remove("stale");
    state.loading = false;
    state.failed = !data && !soft;
    if (data) {
      // offsets shift when an item is added or moved between two requests: never list one twice
      const seen = new Set(reset ? [] : state.items.map((item) => item.id));
      const fresh = [];
      for (const item of data.items) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        fresh.push(item);
      }
      state.items = reset ? fresh : state.items.concat(fresh);
      state.total = data.total;
    } else if (reset && !soft) {
      state.items = [];
      state.total = 0;
    }
    renderList();
  }

  async function loadSections() {
    const data = await attempt(() => api("/notes/sections"));
    if (data) state.sections = data.sections;
    syncChips();
  }

  // Reloads what is on screen (at least as many items, so the scroll position stays valid).
  function refresh() {
    return Promise.all([loadSections(), load(true, Math.max(PAGE, state.items.length), true)]);
  }

  // The server's filter, mirrored: an item that no longer fits is gone before the list is shown again.
  function matchesFilter(item) {
    if (item.status !== state.status) return false;
    return !state.selected.size || item.sections.some((section) => state.selected.has(section.slug));
  }

  // An item keeps its place while it fits the filter (the order is by creation) and leaves the list once not.
  function replaceItem(updated) {
    if (!state.items.some((item) => item.id === updated.id)) return;
    if (matchesFilter(updated)) {
      state.items = state.items.map((item) => (item.id === updated.id ? updated : item));
    } else {
      state.items = state.items.filter((item) => item.id !== updated.id);
      state.total = Math.max(0, state.total - 1);
    }
    renderList();
  }

  function dropItem(id) {
    state.items = state.items.filter((item) => item.id !== id);
    state.total = Math.max(0, state.total - 1);
    renderList();
  }

  // --- item view -----------------------------------------------------------

  // Opens from the list's copy at once, then quietly picks up anything newer from the server.
  function openItem(item) {
    showDetail(item);
    freshen(item.id);
  }

  async function openById(id) {
    const item = await attempt(() => api(`/notes/items/${id}`));
    if (item && launch.alive?.() !== false) showDetail(item);
  }

  async function freshen(id) {
    const version = state.version;
    const rev = state.rev;
    let fresh;
    try {
      fresh = await api(`/notes/items/${id}`);
    } catch (error) {
      if (error instanceof AuthError) handleError(error); // anything else: the copy already on screen will do
      return;
    }
    if (version !== state.version || rev !== state.rev || state.busy) return;
    if (JSON.stringify(fresh) !== JSON.stringify(state.detail)) {
      state.detail = fresh;
      syncDetail(fresh);
    }
  }

  function showDetail(item) {
    state.detail = item;
    state.draft = null;
    state.version += 1;
    state.listScroll = window.scrollY;
    buildDetail();
    syncDetail(item);
    listView.hidden = true;
    detailView.hidden = false;
    setBack(closeDetail);
    window.scrollTo(0, 0);
  }

  function closeDetail() {
    state.version += 1;
    detailView.hidden = true;
    listView.hidden = false;
    setBack(null);
    window.scrollTo(0, state.listScroll);
    if (state.dirty) {
      state.dirty = false;
      refresh();
    }
  }

  // One change at a time: a second tap would be built from state the first one is about to replace.
  async function act(fn) {
    if (state.busy) return undefined;
    state.busy = true;
    const box = detailParts.box; // the card, not the whole view: "← К списку" stays tappable
    box.classList.add("busy");
    try {
      return await attempt(fn);
    } finally {
      state.busy = false;
      box.classList.remove("busy");
    }
  }

  // A change that finishes after the Owner already went back to the list still refreshes it.
  function settle() {
    state.dirty = true;
    if (detailView.hidden) {
      state.dirty = false;
      refresh();
    }
  }

  // `preview` is shown at once and dropped if the server says no; the server's item then replaces it.
  async function patch(body, preview = {}) {
    if (state.busy) return null;
    const version = state.version;
    const before = state.detail;
    state.rev += 1;
    syncDetail({ ...before, ...preview });
    const updated = await act(() => api(`/notes/items/${before.id}`, { method: "PATCH", body }));
    if (version !== state.version) {
      if (updated) settle();
      return updated ?? null;
    }
    if (!updated) {
      syncDetail(before);
      return null;
    }
    state.detail = updated;
    if ("text" in body && detailParts.area.value === body.text) state.draft = null; // else typing went on meanwhile
    syncDetail(updated);
    replaceItem(updated);
    haptic("success");
    settle();
    return updated;
  }

  const detailParts = {};

  function buildDetail() {
    const back = el("button", "btn small ghost", "← К списку");
    back.onclick = closeDetail;
    const box = el("article", "detail");
    const head = el("div", "stack");

    const sectionRow = el("div", "chip-row");
    const sectionButtons = new Map();
    for (const section of state.sections) {
      const chip = el("button", "chip filter", `${section.emoji} ${section.name}`.trim());
      chip.style.setProperty("--chip", section.color);
      chip.onclick = () => toggleSection(section.slug);
      sectionButtons.set(section.slug, chip);
      sectionRow.append(chip);
    }

    const noteTitle = el("h3");
    const field = el("div", "field");
    const area = el("textarea", "textarea");
    area.name = "text";
    area.rows = 4;
    area.maxLength = 4096;
    const save = el("button", "btn small", "Сохранить");
    area.oninput = () => {
      const unchanged = area.value === (state.detail.text || "");
      state.draft = unchanged ? null : area.value;
      save.disabled = unchanged;
    };
    save.onclick = () => patch({ text: area.value });
    field.append(area, save);
    const actions = el("div", "actions");

    box.append(head, el("h3", null, "Секции"), sectionRow, noteTitle, field, actions);
    detailView.replaceChildren(back, box);
    Object.assign(detailParts, { box, head, sectionButtons, noteTitle, area, save, actions });
  }

  async function toggleSection(slug) {
    if (state.busy) return;
    haptic("select");
    const next = new Set(state.detail.sections.map((section) => section.slug));
    const wasOn = next.delete(slug);
    if (!wasOn) next.add(slug);
    const lastOne = wasOn && !next.size && slug !== OTHER;
    const preview = { sections: state.sections.filter((section) => next.has(section.slug)) };
    const updated = await patch({ sections: [...next] }, preview);
    if (updated && lastOne) toast("Перенёс в «Остальное»");
  }

  async function reenrich() {
    if (state.busy) return;
    const version = state.version;
    const id = state.detail.id;
    const slugs = state.detail.sections.map((section) => section.slug);
    const refiles = !slugs.length || (slugs.length === 1 && slugs[0] === OTHER); // the Classifier's rule (ADR-0010)
    state.rev += 1;
    const updated = await act(() => api(`/notes/items/${id}/reenrich`, { method: "POST" }));
    if (!updated) return;
    if (version === state.version) {
      state.detail = updated;
      syncDetail(updated);
      toast(refiles ? "Поставил в очередь" : "Поставил в очередь. Секции оставлю как есть");
    }
    settle();
  }

  async function deleteForever() {
    if (state.busy || !(await confirmAction("Удалить эту запись навсегда?"))) return;
    const version = state.version;
    const id = state.detail.id;
    state.rev += 1;
    const gone = await act(async () => {
      await api(`/notes/items/${id}`, { method: "DELETE" });
      return true;
    });
    if (!gone) return;
    dropItem(id);
    state.dirty = true;
    toast("Удалено");
    if (version === state.version) closeDetail();
    else settle();
  }

  function headNodes(item) {
    const nodes = [];
    const title = itemTitle(item);
    nodes.push(item.kind === "link" && isHttp(item.url) ? externalLink(item, title) : el("h2", "title", title));
    const origin = originOf(item);
    if (origin) nodes.push(el("div", "origin", origin));
    if (item.gist) nodes.push(el("div", "gist", item.gist));
    nodes.push(el("div", "hint", "Сохранено " + fmtDate(item.created_at)));
    if (item.enrichment_status === "pending") {
      nodes.push(enrichmentBadge(item));
    } else {
      if (item.enrichment_status === "failed") nodes.push(enrichmentBadge(item));
      const retry = el("button", "btn small ghost", "Разобрать заново");
      retry.onclick = reenrich;
      nodes.push(retry);
    }
    if (item.tg_message_id) {
      const show = el("button", "btn small ghost", "💬 Показать в чате");
      show.onclick = showInChat;
      nodes.push(show);
    }
    if (item.kind === "voice") nodes.push(el("div", "hint", "🎤 " + fmtDuration(item.duration_s)));
    if (item.transcript) {
      const details = el("details", "caption");
      details.open = true;
      details.append(el("summary", null, "Расшифровка"), el("p", null, item.transcript));
      nodes.push(details);
    }
    if (item.caption) {
      const details = el("details", "caption");
      details.append(el("summary", null, "Описание"), el("p", null, item.caption));
      nodes.push(details);
    }
    return nodes;
  }

  // The bot replies to the original message within a couple of seconds; the app gets out of the way.
  async function showInChat() {
    if (state.busy) return;
    const shown = await act(() => api(`/notes/items/${state.detail.id}/show`, { method: "POST" }));
    if (!shown) return;
    haptic("success");
    tg.close();
  }

  function actionNodes(item) {
    const nodes = [];
    const add = (label, cls, handler) => {
      const button = el("button", "btn small " + cls, label);
      button.onclick = handler;
      nodes.push(button);
    };
    const mark = (status) => () => {
      haptic("select");
      patch({ status }, { status });
    };
    if (item.status === "todo") add("✓ Готово", "", mark("done"));
    else add("↩ Вернуть", "ghost", mark("todo"));
    add("Удалить", "danger", deleteForever);
    return nodes;
  }

  // Brings the open item view in line with `item`: only what differs is touched.
  function syncDetail(item) {
    const { head, sectionButtons, noteTitle, area, save, actions } = detailParts;
    slot(head, JSON.stringify(HEAD_FIELDS.map((field) => item[field])), () => headNodes(item));
    const current = new Set(item.sections.map((section) => section.slug));
    for (const [slug, button] of sectionButtons) button.classList.toggle("on", current.has(slug));
    setText(noteTitle, item.kind === "note" ? "Текст заметки" : "Моя пометка");
    const saved = item.text || "";
    if (state.draft == null && area.value !== saved) area.value = saved;
    save.disabled = area.value === saved;
    slot(actions, item.status, () => actionNodes(item));
  }

  // --- start ---------------------------------------------------------------

  // After a failed first page "Повторить" starts over; after a failed later page it asks for that page again.
  more.onclick = () => load(state.failed && !state.items.length);
  more.hidden = true;
  syncControls();
  await Promise.all([loadSections(), load(true)]);
  if (launch.itemId) await openById(launch.itemId);
}
