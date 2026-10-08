// Заметки: every Section as an accordion with its own Status switch (ADR-0010), Search over all Items, and an edit
// mode that reorders Sections by drag and drop. The state lives in memory for one launch.

import {
  AuthError,
  api,
  attempt,
  el,
  handleError,
  haptic,
  isHalted,
  keepSnapshot,
  pollDelay,
  reconcile,
  setText,
  snapshot,
  toast,
} from "./core.js";
import { OVERDUE, card, sectionLabel } from "./cards.js";
import { openDetail } from "./detail.js";
import { openSectionForm } from "./sections.js";

const PAGE = 30;
const MAX_CHUNK = 100; // the most items the server returns in one request
const SEARCH_DELAY_MS = 300;
const STALE_AFTER_MS = 350;
const EDGE = 56; // a drag this close to the top or bottom of the screen scrolls the page
const STATUSES = [
  ["todo", "Сделать"],
  ["done", "Готово"],
];

// `want` items from `offset`, in requests the server accepts, all under `base`: the chunks after the first go at once.
async function fetchItems(base, offset, want) {
  const chunk = (at, limit) => {
    const query = new URLSearchParams(base);
    query.set("offset", String(at));
    query.set("limit", String(limit));
    return api("/notes/items?" + query);
  };
  const first = await chunk(offset, Math.min(MAX_CHUNK, want));
  const items = [...first.items];
  const end = Math.min(offset + want, first.total);
  const rest = [];
  for (let at = offset + items.length; items.length && at < end; at += MAX_CHUNK) {
    rest.push(chunk(at, Math.min(MAX_CHUNK, end - at)));
  }
  for (const data of await Promise.all(rest)) items.push(...data.items);
  return { items, total: first.total };
}

// ctx.isCurrent() is false while another tab is shown. Returns { show(arg), shown(), hide() };
// arg: { expand: slug } (a Dashboard Section bar) or { itemId } (the ✏️ Открыть button in the chat).
export async function mountNotes(root, ctx) {
  const state = {
    sections: snapshot("sections")?.sections ?? [], // in the Owner's order, each with todo_count and done_count
    expanded: new Set(), // slugs
    status: new Map(), // slug -> Status; a missing slug is on todo
    query: "", // the Search text the results belong to
    results: null, // { items, total } while searching
    folded: new Set(), // slugs the Owner collapsed in the current results
    editing: false,
    overlay: null, // the open item view or Section form
    dirty: false, // something changed under the overlay: refresh once it closes
    after: null, // what shown() does once the pane is on screen
  };
  const groups = new Map(); // slug -> group
  // «Просрочено» is a group too, but not a Section: it lists every Overdue Item once, loaded even while collapsed
  // so its count shows, and it is not on the Owner's list of Sections.
  const overdue = makeGroup({ slug: OVERDUE, name: "Просрочено", emoji: "⏰", color: "var(--danger)", todo_count: 0 });
  overdue.node.classList.add("overdue");
  overdue.switcher.hidden = true;
  groups.set(OVERDUE, overdue);

  const main = el("div");
  const overlay = el("div");
  overlay.hidden = true;
  root.replaceChildren(main, overlay);

  const bar = el("div", "notes-bar");
  const search = el("input", "input search");
  Object.assign(search, { type: "search", placeholder: "Поиск", maxLength: 200, autocomplete: "off" });
  search.enterKeyHint = "search";
  const editButton = el("button", "btn small ghost edit-toggle");
  bar.append(search, editButton);
  const notice = el("p", "hint notice");
  const accordion = el("div", "accordion");
  const empty = el("p", "empty");
  const retryButton = el("button", "btn wide ghost", "Повторить");
  retryButton.hidden = true;
  retryButton.onclick = () => refresh();
  const addButton = el("button", "btn wide ghost", "+ Новая секция");
  main.append(bar, notice, accordion, empty, retryButton, addButton);

  const statusOf = (slug) => state.status.get(slug) || "todo";
  const searching = () => state.results != null && !state.editing;
  const snapshotKey = (g) => (g === overdue ? "overdue" : `group:${g.slug}:${statusOf(g.slug)}`);

  // --- groups --------------------------------------------------------------

  function makeGroup(section) {
    const g = { slug: section.slug, section, items: [], total: 0, loaded: false, loading: false, failed: false };
    g.ticket = 0;
    g.cards = new Map(); // id -> { sig, node }
    g.node = el("section", "group");
    const head = el("div", "group-head");
    g.handle = el("span", "handle", "⋮⋮");
    g.handle.setAttribute("aria-label", "Перетащить");
    g.toggle = el("button", "group-toggle");
    g.caret = el("span", "caret");
    g.label = el("span", "group-name");
    g.count = el("span", "group-n");
    g.toggle.append(g.caret, g.label, g.count);
    g.edit = el("button", "btn small ghost group-edit", "✏️");
    g.edit.setAttribute("aria-label", "Изменить секцию");
    head.append(g.handle, g.toggle, g.edit);

    g.switcher = el("div", "segmented");
    g.segs = new Map();
    for (const [value, label] of STATUSES) {
      const button = el("button", "seg", label);
      button.onclick = () => setStatus(g, value);
      g.segs.set(value, button);
      g.switcher.append(button);
    }
    g.list = el("div", "cards");
    g.note = el("p", "empty");
    g.more = el("button", "btn wide ghost", "Ещё");
    g.body = el("div", "group-body");
    g.body.append(g.switcher, g.list, g.more);
    g.node.append(head, g.body);

    g.toggle.onclick = () => toggleGroup(g);
    g.edit.onclick = () => openForm(g.section);
    // After a failed first page "Повторить" starts over; after a failed later page it asks for that page again.
    g.more.onclick = () => loadGroup(g, g.failed && !g.items.length);
    g.handle.onpointerdown = (event) => startDrag(g, event);
    g.handle.onpointermove = moveDrag;
    g.handle.onpointerup = () => endDrag(false);
    g.handle.onpointercancel = () => endDrag(true);
    return g;
  }

  function cardFor(g, item, marked) {
    const sig = JSON.stringify(item) + marked;
    const hit = g.cards.get(item.id);
    if (hit && hit.sig === sig) return hit.node;
    const node = card(item, { open: openItem, changed: itemChanged, under: g.slug, markDone: marked });
    g.cards.set(item.id, { sig, node });
    return node;
  }

  function groupNote(g) {
    if (g.loading || !g.loaded) return "Загрузка…";
    if (g.failed) return "Не удалось загрузить.";
    return "Тут пусто.";
  }

  function renderGroup(g, found) {
    const status = statusOf(g.slug);
    const inSearch = found != null;
    const open = !state.editing && (inSearch ? !state.folded.has(g.slug) : state.expanded.has(g.slug));
    const n = inSearch ? found.length : g.section[status + "_count"] || 0;
    g.node.style.setProperty("--chip", g.section.color);
    g.node.classList.toggle("dim", n === 0);
    g.node.classList.toggle("open", open);
    setText(g.label, sectionLabel(g.section));
    setText(g.count, String(n));
    setText(g.caret, open ? "▾" : "▸");
    g.caret.hidden = state.editing;
    g.handle.hidden = !state.editing;
    g.edit.hidden = !state.editing;
    g.toggle.disabled = state.editing;
    g.body.hidden = !open;
    if (!open) return;

    g.switcher.hidden = inSearch || g === overdue;
    for (const [value, button] of g.segs) button.classList.toggle("on", value === status);
    const items = inSearch ? found : g.items;
    const live = new Set(items.map((item) => item.id));
    for (const id of g.cards.keys()) if (!live.has(id)) g.cards.delete(id);
    let nodes = items.map((item) => cardFor(g, item, inSearch));
    if (!nodes.length) {
      setText(g.note, groupNote(g));
      nodes = [g.note];
    }
    reconcile(g.list, nodes);
    g.more.hidden = inSearch || !g.loaded || (!g.failed && g.items.length >= g.total);
    g.more.disabled = g.loading;
    setText(g.more, g.failed ? "Повторить" : "Ещё");
  }

  // Search results by Section: an Item filed under two Sections shows under both (ADR-0002).
  function resultsBySection() {
    const found = new Map();
    for (const item of state.results.items) {
      for (const section of item.sections) {
        if (!found.has(section.slug)) found.set(section.slug, []);
        found.get(section.slug).push(item);
      }
    }
    return found;
  }

  function render() {
    const found = searching() ? resultsBySection() : null;
    const nodes = [];
    if (!found && !state.editing) {
      renderGroup(overdue, null);
      if (overdue.section.todo_count > 0) nodes.push(overdue.node);
    }
    for (const section of state.sections) {
      let g = groups.get(section.slug);
      if (!g) {
        g = makeGroup(section);
        groups.set(section.slug, g);
      }
      g.section = section;
      if (found && !found.has(section.slug)) continue;
      renderGroup(g, found?.get(section.slug));
      nodes.push(g.node);
    }
    const slugs = new Set(state.sections.map((section) => section.slug));
    for (const slug of groups.keys()) if (slug !== OVERDUE && !slugs.has(slug)) groups.delete(slug);
    if (!drag) reconcile(accordion, nodes);

    search.hidden = state.editing;
    setText(editButton, state.editing ? "Готово" : "Изменить");
    addButton.hidden = !state.editing;
    accordion.classList.toggle("editing", state.editing);
    const capped = found && state.results.total > state.results.items.length;
    notice.hidden = !capped;
    if (capped) setText(notice, `Показаны первые ${state.results.items.length} из ${state.results.total}. Уточни запрос.`);
    empty.hidden = nodes.length > 0;
    setText(empty, found ? "Ничего не нашлось." : sectionsFailed ? "Не удалось загрузить секции." : "Загрузка…");
    retryButton.hidden = !(sectionsFailed && !nodes.length);
    schedulePoll();
  }

  // --- loading -------------------------------------------------------------

  // A reset keeps the old list on screen until the new one arrives, then swaps it once.
  // `want` is how many items a reset brings back; `soft` keeps the list if the request fails.
  async function loadGroup(g, reset, want = PAGE, soft = false) {
    if (!reset && g.loading) return;
    const ticket = ++g.ticket;
    const status = statusOf(g.slug);
    const key = snapshotKey(g);
    const kept = reset && !g.loaded ? snapshot(key) : null;
    if (kept) {
      // the last launch's list shows at once; the fresh one replaces it below
      g.items = kept.items;
      g.total = kept.total;
      g.loaded = true;
      g.section[status + "_count"] = kept.total;
    }
    g.loading = true;
    g.more.disabled = true;
    if (kept) render();
    const dim = () => {
      if (ticket === g.ticket) g.list.classList.add("stale");
    };
    const staleTimer = reset && g.items.length && !kept ? setTimeout(dim, STALE_AFTER_MS) : null;
    const base = g === overdue ? new URLSearchParams({ overdue: "true" }) : new URLSearchParams({ section: g.slug, status });
    const data = await attempt(() => fetchItems(base, reset ? 0 : g.items.length, want));
    clearTimeout(staleTimer);
    if (ticket !== g.ticket) return;
    g.list.classList.remove("stale");
    g.loading = false;
    g.failed = !data && !soft && !kept;
    if (data) {
      // offsets shift when an item is added or moved between two requests: never list one twice
      const seen = new Set(reset ? [] : g.items.map((item) => item.id));
      const fresh = data.items.filter((item) => !seen.has(item.id) && seen.add(item.id));
      g.items = reset ? fresh : g.items.concat(fresh);
      g.total = data.total;
      g.loaded = true;
      g.section[status + "_count"] = data.total;
      if (reset) keepSnapshot(key, { items: g.items.slice(0, PAGE), total: g.total });
    } else if (reset && !kept && (!soft || !g.loaded)) {
      g.items = [];
      g.total = 0;
      g.loaded = true;
      g.failed = true;
    }
    render();
  }

  let sectionsTicket = 0;
  let orderGen = 0; // bumps when an order save starts or ends: a list read across it may hold the old order
  let sectionsFailed = false;
  async function loadSections() {
    const ticket = ++sectionsTicket;
    const gen = orderGen;
    const data = await attempt(() => api("/notes/sections"));
    if (ticket !== sectionsTicket) return;
    sectionsFailed = !data && !state.sections.length;
    if (data && gen === orderGen && !drag && !orderSaving) {
      state.sections = data.sections;
      keepSnapshot("sections", data); // only an answer the page took: an older order is never kept
    }
    render();
  }

  let searchTicket = 0;
  async function runSearch(query) {
    const ticket = ++searchTicket;
    const data = await attempt(() => api("/notes/items?" + new URLSearchParams({ q: query, limit: MAX_CHUNK })));
    if (ticket !== searchTicket || !data || query !== search.value.trim()) return; // what is typed now wins
    if (query !== state.query) state.folded = new Set();
    state.query = query;
    state.results = data;
    render();
  }

  // Reloads what is on screen, all at once: the counts, the open Sections (as many items as they show) and the
  // results. A collapsed Section reloads when it opens again. A call while one runs makes it go once more.
  let refreshing = null;
  let refreshAgain = false;
  async function refresh() {
    if (refreshing) {
      refreshAgain = true;
      return refreshing;
    }
    let finish;
    refreshing = new Promise((resolve) => {
      finish = resolve;
    }); // set before the first render below, so no poll is armed meanwhile
    try {
      do {
        refreshAgain = false;
        await refreshOnce();
      } while (refreshAgain);
    } finally {
      refreshing = null;
      finish();
      schedulePoll(); // held back while the refresh ran: it brought the fresh state itself
    }
  }

  async function refreshOnce() {
    render(); // a group for every Section known so far, so the open ones load alongside the counts
    const started = new Set();
    const jobs = [loadSections()];
    for (const g of groups.values()) {
      if (state.expanded.has(g.slug) || g === overdue) {
        started.add(g);
        jobs.push(loadGroup(g, true, Math.max(PAGE, g.items.length), true));
      } else {
        g.ticket += 1; // an expand load still in flight answers from before the change
        g.loading = false;
        g.loaded = false;
      }
    }
    const query = search.value.trim();
    if (query) jobs.push(runSearch(query));
    await Promise.all(jobs);
    // An open Section the page only learnt of from the reply above (a first launch) loads now.
    const late = [...groups.values()].filter(
      (g) => state.expanded.has(g.slug) && !started.has(g) && !g.loaded && !g.loading,
    );
    await Promise.all(late.map((g) => loadGroup(g, true)));
  }

  // --- the Owner's taps ------------------------------------------------------

  function toggleGroup(g) {
    haptic("select");
    if (searching()) {
      if (!state.folded.delete(g.slug)) state.folded.add(g.slug);
    } else if (!state.expanded.delete(g.slug)) {
      state.expanded.add(g.slug);
      if (!g.loaded) loadGroup(g, true);
    }
    render();
  }

  function setStatus(g, value) {
    if (statusOf(g.slug) === value) return;
    haptic("select");
    state.status.set(g.slug, value);
    g.loaded = false; // the other Status's kept list, if any, shows at once
    loadGroup(g, true);
    render();
  }

  let searchTimer = 0;
  search.oninput = () => {
    clearTimeout(searchTimer);
    const query = search.value.trim();
    if (!query) {
      searchTicket += 1; // drop any answer still on its way
      state.query = "";
      state.results = null;
      render();
      return;
    }
    if (query === state.query && state.results) {
      searchTicket += 1; // an answer for what was typed in between must not land
      return;
    }
    searchTimer = setTimeout(() => runSearch(query), SEARCH_DELAY_MS);
  };
  search.onkeydown = (event) => {
    if (event.key === "Enter") search.blur(); // closes the keyboard; the results are already there
  };

  editButton.onclick = () => {
    haptic("select");
    state.editing = !state.editing;
    render();
  };
  addButton.onclick = () => openForm(null);

  // --- overlays: the item view and the Section form --------------------------

  // `fresh`: the item was fetched just now, so the view need not ask for it again.
  function openItem(item, fresh = false) {
    state.overlay = openDetail({
      list: main,
      host: overlay,
      item,
      fresh,
      sections: state.sections,
      changed: itemChanged,
      deleted: itemDeleted,
      closed: overlayClosed,
      visible: ctx.isCurrent,
    });
  }

  function openForm(section) {
    state.overlay = openSectionForm({
      list: main,
      host: overlay,
      section,
      saved: () => {
        state.dirty = true;
      },
      closed: overlayClosed,
    });
  }

  function overlayClosed() {
    state.overlay = null;
    if (state.dirty) {
      state.dirty = false;
      refresh();
    }
    schedulePoll();
  }

  const fits = (item, g) =>
    g === overdue ? item.overdue : item.status === statusOf(g.slug) && item.sections.some((s) => s.slug === g.slug);

  // An item keeps its place while it still fits a Section's list and leaves it once not; the refresh that follows
  // brings it into the lists it moved to and corrects the counts.
  function itemChanged(updated) {
    localGen += 1;
    for (const g of groups.values()) {
      const at = g.items.findIndex((item) => item.id === updated.id);
      if (at < 0) continue;
      if (fits(updated, g)) g.items[at] = updated;
      else {
        g.items.splice(at, 1);
        g.total = Math.max(0, g.total - 1);
        if (g === overdue) g.section.todo_count = g.total;
      }
    }
    if (state.results) {
      state.results.items = state.results.items.map((item) => (item.id === updated.id ? updated : item));
    }
    changed();
  }

  function itemDeleted(id) {
    localGen += 1;
    for (const g of groups.values()) {
      const before = g.items.length;
      g.items = g.items.filter((item) => item.id !== id);
      g.total = Math.max(0, g.total - (before - g.items.length));
      if (g === overdue) g.section.todo_count = g.total;
    }
    if (state.results) {
      const before = state.results.items.length;
      state.results.items = state.results.items.filter((item) => item.id !== id);
      state.results.total -= before - state.results.items.length;
    }
    changed();
  }

  function changed() {
    render();
    if (state.overlay) state.dirty = true;
    else refresh();
  }

  // --- pending items and coming back to the app --------------------------------

  // Only the pending Items shown are asked about, less often each time; one that settles brings a refresh,
  // since the Classifier may have filed it elsewhere.
  let pollTimer = 0;
  let pollStep = 0;
  let polling = false;
  let localGen = 0; // bumps on each change made here: a poll reply sent before one is stale
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (refreshing || state.overlay || drag || !ctx.isCurrent() || isHalted()) return;
    if (document.visibilityState !== "visible") return;
    const shown = searching()
      ? state.results.items
      : [...groups.values()].filter((g) => state.expanded.has(g.slug)).flatMap((g) => g.items);
    const pending = shown.filter((item) => item.enrichment_status === "pending");
    if (!pending.length) {
      pollStep = 0;
      return;
    }
    const delay = pollDelay(pollStep, pending);
    const ids = [...new Set(pending.map((item) => item.id))].slice(0, MAX_CHUNK); // what the server takes at once
    pollTimer = setTimeout(() => pollPending(ids), delay);
  }

  async function pollPending(ids) {
    if (polling) return;
    polling = true;
    pollStep += 1;
    const gen = localGen;
    let data = null;
    try {
      data = await api("/notes/items?" + new URLSearchParams(ids.map((id) => ["ids", String(id)])));
    } catch (error) {
      if (error instanceof AuthError) handleError(error); // anything else: the next tick asks again
    } finally {
      polling = false;
    }
    if (!data || gen !== localGen) {
      schedulePoll(); // a change made meanwhile brings its own refresh
      return;
    }
    const back = new Map(data.items.map((item) => [item.id, item]));
    if (ids.some((id) => back.get(id)?.enrichment_status !== "pending")) {
      pollStep = 0;
      refresh();
      return;
    }
    for (const g of groups.values()) g.items = g.items.map((item) => back.get(item.id) ?? item);
    if (state.results) state.results.items = state.results.items.map((item) => back.get(item.id) ?? item);
    render();
  }

  // Back in the app after sending something in the chat: show what arrived meanwhile.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !ctx.isCurrent() || state.overlay || drag) return;
    pollStep = 0;
    refresh();
  });

  // --- drag and drop (edit mode) ---------------------------------------------

  let drag = null;
  let orderSaving = false;

  function startDrag(g, event) {
    if (!state.editing || drag || orderSaving || state.sections.length < 2) return;
    event.preventDefault();
    const nodes = [...accordion.children];
    const from = nodes.indexOf(g.node);
    const tops = nodes.map((node) => node.getBoundingClientRect().top);
    drag = {
      g,
      nodes,
      from,
      to: from,
      pitch: tops[1] - tops[0],
      startY: event.clientY,
      startScroll: window.scrollY,
      y: event.clientY,
      pointerId: event.pointerId,
      frame: 0,
    };
    g.handle.setPointerCapture(event.pointerId);
    accordion.classList.add("sorting");
    g.node.classList.add("dragging");
    haptic("select");
    drag.frame = requestAnimationFrame(autoScroll);
  }

  function moveDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.y = event.clientY;
    place();
  }

  // The dragged header follows the finger; the others slide over to show where it would land.
  function place() {
    const { g, nodes, from, pitch } = drag;
    const last = nodes.length - 1;
    const raw = drag.y - drag.startY + (window.scrollY - drag.startScroll);
    const dy = Math.max(-from * pitch, Math.min((last - from) * pitch, raw));
    g.node.style.transform = `translateY(${dy}px)`;
    const to = Math.max(0, Math.min(last, Math.round(from + dy / pitch)));
    if (to !== drag.to) {
      drag.to = to;
      haptic("select");
    }
    nodes.forEach((node, i) => {
      if (node === g.node) return;
      let shift = 0;
      if (from < to && i > from && i <= to) shift = -pitch;
      if (from > to && i >= to && i < from) shift = pitch;
      node.style.transform = shift ? `translateY(${shift}px)` : "";
    });
  }

  function autoScroll() {
    if (!drag) return;
    const step = drag.y < EDGE ? -8 : drag.y > window.innerHeight - EDGE ? 8 : 0;
    if (step) {
      const before = window.scrollY;
      window.scrollBy(0, step);
      if (window.scrollY !== before) place();
    }
    drag.frame = requestAnimationFrame(autoScroll);
  }

  function endDrag(cancelled) {
    if (!drag) return;
    const { g, nodes, from, to, frame } = drag;
    cancelAnimationFrame(frame);
    drag = null;
    accordion.classList.remove("sorting");
    g.node.classList.remove("dragging");
    for (const node of nodes) node.style.transform = "";
    if (cancelled || to === from) {
      render();
      return;
    }
    const next = [...state.sections];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    saveOrder(next);
  }

  // The new order shows at once; the server's answer confirms it, or the old order comes back.
  async function saveOrder(next) {
    const before = state.sections;
    state.sections = next;
    render();
    orderSaving = true;
    orderGen += 1;
    try {
      await api("/notes/sections/order", { method: "PUT", body: { ids: next.map((section) => section.id) } });
      keepSnapshot("sections", { sections: next });
      haptic("success");
    } catch (error) {
      state.sections = before;
      render();
      if (error instanceof AuthError) handleError(error);
      else toast("Не удалось сохранить порядок");
    } finally {
      orderSaving = false;
      orderGen += 1;
    }
    if (state.sections === before) loadSections(); // the server may know a list this page does not
  }

  // --- the tab ---------------------------------------------------------------

  // Once the Sections are known (kept from the last launch), the tab shows at once and the refresh runs behind it.
  async function show(arg = {}) {
    state.after = null;
    if (arg.expand) {
      // a Section bar on the Dashboard: that Section open on «Сделать», nothing hiding it
      state.editing = false;
      search.value = "";
      state.query = "";
      state.results = null;
      searchTicket += 1;
      state.expanded.add(arg.expand);
      state.status.set(arg.expand, "todo");
    }
    // the chat's ✏️ asks for one Item: it is fetched alongside the lists, never after them
    const wanted = arg.itemId ? attempt(() => api(`/notes/items/${arg.itemId}`)) : null;
    const loading = refresh();
    const unknown = arg.expand && !state.sections.some((section) => section.slug === arg.expand);
    if (!state.sections.length || unknown) await loading; // the Section to open must exist before the scroll
    if (arg.expand) {
      state.after = () => groups.get(arg.expand)?.node.scrollIntoView({ block: "start" });
    } else if (wanted) {
      const item = await wanted;
      if (item) state.after = () => openItem(item, true);
    }
  }

  function shown() {
    const after = state.after;
    state.after = null;
    after?.();
    schedulePoll();
  }

  function hide() {
    clearTimeout(pollTimer);
    endDrag(true);
    state.overlay?.close();
  }

  return { show, shown, hide };
}
