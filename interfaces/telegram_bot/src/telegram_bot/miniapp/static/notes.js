// Заметки: the Section rail and one Section's rows in one Status (ADR-021, notes ADR-0010), Search over all Items,
// and an edit mode that reorders Sections by drag and drop. The Section picked and the rail are remembered across
// launches (core.js prefs); everything else lives in memory for one launch.

import {
  AuthError,
  api,
  attempt,
  confirmAction,
  el,
  handleError,
  haptic,
  isHalted,
  keepSnapshot,
  pollDelay,
  prefs,
  reconcile,
  savePrefs,
  setText,
  snapshot,
  tg,
  toast,
} from "./core.js";
import { OVERDUE, reenrichToast, row, sectionLabel } from "./cards.js";
import { openDetail } from "./detail.js";
import { openMenu } from "./nav.js";
import { attachRowActions } from "./rowactions.js";
import { openSectionForm } from "./sections.js";

const PAGE = 30;
const MAX_CHUNK = 100; // the most items the server returns in one request
const SEARCH_DELAY_MS = 300;
const STALE_AFTER_MS = 350;
const EDGE = 56; // a drag this close to the top or bottom of the screen scrolls the page

// The Lists this mode shows (CONTEXT: List), each with its request. A kept List's snapshot key (ADR-019) is the one
// earlier builds wrote, so the last launch's list still paints after a deploy; Search and a Recheck are never kept.
const LISTS = {
  overdue: () => ({ key: "overdue", params: { overdue: "true" } }),
  inSection: (slug, status) => ({ key: `group:${slug}:${status}`, params: { section: slug, status } }),
  search: (q) => ({ params: { q, limit: String(MAX_CHUNK) } }),
  recheck: (ids) => ({ params: ids.map((id) => ["ids", String(id)]) }),
};

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

// What stands for a Section on the rail and in the Section menu: its emoji, else the first two letters of its name.
const markOf = (section) => section.emoji || Array.from(section.name.trim()).slice(0, 2).join("");

// ctx.isCurrent() is false while another view shows; ctx.setBar() sets this view's part of the title row.
// Returns { show(arg), shown(), hide() }; arg: { section: slug } (a Dashboard Section bar or «просрочено») or
// { itemId } (the 📅 Перенести button in the chat).
export async function mountNotes(root, ctx) {
  const state = {
    sections: snapshot("sections")?.sections ?? [], // in the Owner's order, each with todo_count and done_count
    section: prefs().section ?? null, // the slug picked last, or OVERDUE; selected() says which one shows
    stay: false, // «Просрочено» was picked in this launch: it stays on screen even once nothing is Overdue
    status: "todo", // one Status for the whole list; «Готово» is not remembered
    rail: prefs().rail !== false,
    query: "", // the Search text the results belong to
    results: null, // { items, total } while searching
    searchOpen: false, // the Search field stands in for the title row
    editing: false,
    overlay: null, // the open item view or Section form
    dirty: false, // something changed under the overlay or during a write: refresh once it is over
    writes: 0, // Status changes not answered yet: a list read meanwhile would undo them on screen
    after: null, // what shown() does once the pane is on screen
  };
  const groups = new Map(); // slug -> group
  // «Просрочено» is a group too, but not a Section: it lists every Overdue Item once, loaded even while another
  // Section shows so its count is known, and it is not on the Owner's list of Sections.
  const overdue = makeGroup({ slug: OVERDUE, name: "Просрочено", emoji: "⏰", color: "var(--danger)", todo_count: 0 });
  groups.set(OVERDUE, overdue);

  const main = el("div");
  const overlay = el("div");
  overlay.hidden = true;
  root.replaceChildren(main, overlay);

  // This view's part of the title row: «◧» and «🔍»; the Search field or «Секции · Готово» in place of the row.
  const railToggle = el("button", "icon-btn", "◧");
  railToggle.setAttribute("aria-label", "Полоса секций");
  const searchButton = el("button", "icon-btn", "🔍");
  searchButton.setAttribute("aria-label", "Поиск");
  const search = el("input", "input");
  Object.assign(search, { type: "search", placeholder: "Поиск", maxLength: 200, autocomplete: "off" });
  search.enterKeyHint = "search";
  const cancelSearch = el("button", "btn small ghost", "Отмена");
  const editDone = el("button", "btn small ghost", "Готово");
  const editRight = el("div", "right");
  editRight.append(editDone);
  const editBar = [el("h1", null, "Секции"), editRight];

  const rail = el("nav", "rail");
  const railButtons = new Map(); // slug -> button
  const railOverdue = railButton("⏰", "Просрочено", () => pick(OVERDUE));
  railOverdue.style.setProperty("--chip", "var(--danger)");
  const railDone = railButton("✓", "Готово", toggleDone);
  railDone.classList.add("done");
  railDone.style.setProperty("--chip", "var(--good)");
  const railEdit = railButton("✏️", "Правка секций", startEditing);
  railEdit.classList.add("small");
  const railSep = el("div", "rail-sep");

  const secHead = makeHead("div"); // with the rail: a caption
  const secButton = makeHead("button"); // without it: opens the list of Sections
  secButton.node.onclick = openSectionMenu;
  const notice = el("p", "hint notice");
  const groupsBox = el("div", "groups");
  const empty = el("p", "empty");
  const retryButton = el("button", "btn wide ghost", "Повторить");
  retryButton.hidden = true;
  retryButton.onclick = () => refresh();
  const addButton = el("button", "btn wide ghost", "+ Новая секция");
  const listCol = el("div", "list-col");
  listCol.append(secHead.node, secButton.node, notice, groupsBox, empty, retryButton, addButton);
  const notes = el("div", "notes");
  notes.append(rail, listCol);
  main.append(notes);

  const statusOf = (slug) => (slug === OVERDUE ? "todo" : state.status);
  const searching = () => state.results != null && !state.editing;
  const listOf = (g) => (g === overdue ? LISTS.overdue() : LISTS.inSection(g.slug, statusOf(g.slug)));

  // The Section on screen: the one picked last while it is still there, else the first with something to do.
  function selected() {
    if (state.section === OVERDUE) {
      if (state.stay || !overdue.loaded || overdue.section.todo_count > 0) return OVERDUE;
    } else if (state.sections.some((section) => section.slug === state.section)) {
      return state.section;
    }
    return (state.sections.find((section) => section.todo_count > 0) ?? state.sections[0])?.slug ?? null;
  }

  // The Items on screen: the results while searching, else the selected Section's.
  const shownItems = () => (searching() ? state.results.items : (groups.get(selected())?.items ?? []));

  function railButton(text, label, onclick) {
    const button = el("button", null, text);
    button.setAttribute("aria-label", label);
    button.onclick = onclick;
    return button;
  }

  // A Section's caption: its name, «· готово» on the done list, the number of Items.
  function makeHead(tag) {
    const node = el(tag, "sec-head");
    const name = el("span", "name");
    const st = el("span", "st", "· готово");
    const n = el("span", "n");
    node.append(name, st, n);
    if (tag === "button") node.append(el("span", "caret"));
    return { node, name, st, n };
  }

  // --- groups --------------------------------------------------------------

  // A Section's rows, plus its two other faces: the caption over its Search results and its row in edit mode.
  function makeGroup(section) {
    const g = { slug: section.slug, section, items: [], total: 0, loaded: false, loading: false, failed: false };
    g.held = false; // `items` is this launch's list for the Status shown: the kept one is older
    g.ticket = 0;
    g.nodes = new Map(); // id -> { sig, node }
    g.list = el("div", "rows");
    g.note = el("p", "empty");
    g.more = el("button", "btn wide ghost", "Ещё");
    // After a failed first page "Повторить" starts over; after a failed later page it asks for that page again.
    g.more.onclick = () => loadGroup(g, g.failed && !g.items.length);

    g.found = el("section", "group");
    g.foundHead = makeHead("div");
    g.foundHead.st.hidden = true;
    g.found.append(g.foundHead.node);

    g.node = el("section", "group");
    const head = el("div", "group-head");
    g.handle = el("span", "handle", "⋮⋮");
    g.handle.setAttribute("aria-label", "Перетащить");
    g.label = el("span", "group-name");
    g.count = el("span", "group-n");
    g.edit = el("button", "btn small ghost group-edit", "✏️");
    g.edit.setAttribute("aria-label", "Изменить секцию");
    head.append(g.handle, g.label, g.count, g.edit);
    g.node.append(head);
    g.edit.onclick = () => openForm(g.section);
    g.handle.onpointerdown = (event) => startDrag(g, event);
    g.handle.onpointermove = moveDrag;
    g.handle.onpointerup = () => endDrag(false);
    g.handle.onpointercancel = () => endDrag(true);
    return g;
  }

  function rowFor(g, item, marked) {
    const sig = JSON.stringify(item) + marked;
    const hit = g.nodes.get(item.id);
    if (hit && hit.sig === sig) return hit.node;
    const node = row(item, { markDone: marked });
    g.nodes.set(item.id, { sig, node });
    return node;
  }

  function fillList(g, items, marked) {
    const live = new Set(items.map((item) => item.id));
    for (const id of g.nodes.keys()) if (!live.has(id)) g.nodes.delete(id);
    reconcile(g.list, items.map((item) => rowFor(g, item, marked))); // prettier-ignore
  }

  function groupNote(g) {
    if (g.loading || !g.loaded) return "Загрузка…";
    if (g.failed) return "Не удалось загрузить.";
    return "Тут пусто.";
  }

  // The selected Section: its rows or a line saying why there are none, then «Ещё».
  function listNodes(g) {
    fillList(g, g.items, false);
    setText(g.note, groupNote(g));
    g.more.disabled = g.loading;
    setText(g.more, g.failed ? "Повторить" : "Ещё");
    const nodes = [g.items.length ? g.list : g.note];
    if (g.loaded && (g.failed || g.items.length < g.total)) nodes.push(g.more);
    return nodes;
  }

  function foundNode(g, items) {
    setText(g.foundHead.name, sectionLabel(g.section));
    setText(g.foundHead.n, String(items.length));
    fillList(g, items, true);
    if (g.list.parentNode !== g.found) g.found.append(g.list);
    return g.found;
  }

  function editNode(g) {
    g.node.style.setProperty("--chip", g.section.color);
    g.node.classList.toggle("dim", !g.section.todo_count);
    setText(g.label, sectionLabel(g.section));
    setText(g.count, String(g.section.todo_count || 0));
    return g.node;
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

  function paintHead({ node, name, st, n }, g) {
    const status = statusOf(g.slug);
    node.classList.toggle("overdue", g === overdue);
    setText(name, sectionLabel(g.section));
    st.hidden = status !== "done";
    setText(n, String(g.section[status + "_count"] || 0));
  }

  function renderRail(slug) {
    const nodes = [];
    if (overdue.section.todo_count > 0 || slug === OVERDUE) nodes.push(railOverdue);
    for (const section of state.sections) {
      let button = railButtons.get(section.slug);
      if (!button) {
        button = railButton("", section.name, () => pick(section.slug));
        railButtons.set(section.slug, button);
      }
      setText(button, markOf(section));
      button.setAttribute("aria-label", section.name);
      button.title = section.name;
      button.style.setProperty("--chip", section.color);
      button.classList.toggle("abbr", !section.emoji);
      button.classList.toggle("on", section.slug === slug);
      button.classList.toggle("dim", !section.todo_count);
      nodes.push(button);
    }
    for (const key of railButtons.keys()) if (!groups.has(key)) railButtons.delete(key);
    railOverdue.classList.toggle("on", slug === OVERDUE);
    railDone.classList.toggle("on", state.status === "done" && slug !== OVERDUE);
    railDone.disabled = slug === OVERDUE;
    reconcile(rail, [...nodes, railSep, railDone, railEdit]);
  }

  let barMode = null;
  // The title row is set only when its kind changes: setting it again would take the focus out of the Search field.
  function paintBar() {
    const mode = state.editing ? "edit" : state.searchOpen ? "search" : "list";
    if (mode === barMode) return;
    barMode = mode;
    if (mode === "edit") ctx.setBar({ replace: editBar });
    else if (mode === "search") ctx.setBar({ replace: [search, cancelSearch] });
    else ctx.setBar({ left: [railToggle], right: [searchButton] });
  }

  let rowActions = null;
  let face = null; // which list is on screen: an open swipe panel does not outlive it

  function render() {
    for (const section of state.sections) {
      let g = groups.get(section.slug);
      if (!g) {
        g = makeGroup(section);
        groups.set(section.slug, g);
      }
      g.section = section;
    }
    const slugs = new Set(state.sections.map((section) => section.slug));
    for (const slug of groups.keys()) if (slug !== OVERDUE && !slugs.has(slug)) groups.delete(slug);

    const found = searching() ? resultsBySection() : null;
    const plain = !found && !state.editing; // one Section's rows, under the rail or the Section menu
    const slug = selected();
    const next = state.editing ? "edit" : found ? "search" : `${slug}:${state.status}`;
    if (next !== face) rowActions?.close();
    face = next;
    const current = plain ? (groups.get(slug) ?? null) : null;
    let nodes = [];
    if (state.editing) {
      nodes = state.sections.map((section) => editNode(groups.get(section.slug)));
    } else if (found) {
      nodes = state.sections
        .filter((section) => found.has(section.slug))
        .map((section) => foundNode(groups.get(section.slug), found.get(section.slug)));
    } else if (current) {
      nodes = listNodes(current);
    }
    if (!drag) reconcile(groupsBox, nodes);
    groupsBox.classList.toggle("editing", state.editing);

    rail.hidden = !plain || !state.rail || !state.sections.length;
    if (!rail.hidden) renderRail(slug);
    railToggle.classList.toggle("on", state.rail);
    railToggle.setAttribute("aria-pressed", String(state.rail));
    secHead.node.hidden = !current || !state.rail;
    secButton.node.hidden = !current || state.rail;
    if (current) for (const head of [secHead, secButton]) paintHead(head, current);
    addButton.hidden = !state.editing;
    const capped = found && state.results.total > state.results.items.length;
    notice.hidden = !capped;
    if (capped) setText(notice, `Показаны первые ${state.results.items.length} из ${state.results.total}. Уточни запрос.`);
    empty.hidden = nodes.length > 0;
    setText(empty, found ? "Ничего не нашлось." : sectionsFailed ? "Не удалось загрузить секции." : "Загрузка…");
    retryButton.hidden = !(sectionsFailed && !nodes.length);
    paintBar();
    schedulePoll();
  }

  // --- loading -------------------------------------------------------------

  // A reset keeps the old list on screen until the new one arrives, then swaps it once.
  // `want` is how many items a reset brings back; `soft` keeps the list if the request fails.
  async function loadGroup(g, reset, want = PAGE, soft = false) {
    if (!reset && g.loading) return;
    const ticket = ++g.ticket;
    const status = statusOf(g.slug);
    const { key, params } = listOf(g);
    const kept = reset && !g.loaded && !g.held ? snapshot(key) : null;
    if (kept) {
      // the last launch's list shows at once; the fresh one replaces it below
      g.items = kept.items;
      g.total = kept.total;
      g.held = true;
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
    const data = await attempt(() => fetchItems(params, reset ? 0 : g.items.length, want));
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
      g.held = true;
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
    const data = await attempt(() => api("/notes/items?" + new URLSearchParams(LISTS.search(query).params)));
    if (ticket !== searchTicket || !data || query !== search.value.trim()) return; // what is typed now wins
    state.query = query;
    state.results = data;
    render();
  }

  // Reloads what is on screen, all at once: the counts, the Section shown (as many items as it shows), «Просрочено»
  // for its count, and the results. Another Section reloads when it is picked. A call while one runs makes it go
  // once more.
  let refreshing = null;
  let refreshAgain = false;
  async function refresh() {
    if (state.writes) {
      state.dirty = true; // the answer of the change in flight starts this refresh itself
      return undefined;
    }
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
    render(); // a group for every Section known so far, so the one shown loads alongside the counts
    const started = new Set();
    const jobs = [loadSections()];
    const slug = selected();
    for (const g of groups.values()) {
      if (g.slug === slug || g === overdue) {
        started.add(g);
        jobs.push(loadGroup(g, true, Math.max(PAGE, g.items.length), true));
      } else {
        g.ticket += 1; // a load still in flight answers from before the change
        g.loading = false;
        g.loaded = false;
      }
    }
    const query = search.value.trim();
    if (query && state.searchOpen) jobs.push(runSearch(query));
    await Promise.all(jobs);
    // The Section to show may be known only from the replies above: a first launch, nothing Overdue any more.
    pin();
    const late = groups.get(selected());
    if (late && !started.has(late) && !late.loaded && !late.loading) await loadGroup(late, true);
  }

  // The Section shown when none was picked stays the same from the first answer on: closing its last Item, or a
  // new order of Sections, must not swap the list under the Owner. Memory only: a launch chooses again.
  function pin() {
    const slug = selected();
    if (!slug) return;
    state.section = slug;
    if (slug === OVERDUE) state.stay = true;
  }

  // --- the Owner's taps ------------------------------------------------------

  function loadSelected() {
    if (state.writes) return; // the answer of the change in flight starts a refresh, which reads this Section
    const g = groups.get(selected());
    if (g && !g.loaded && !g.loading) loadGroup(g, true);
  }

  // One Status for the whole list: what every Section holds belongs to the other one from here on.
  function setStatus(value) {
    if (state.status === value) return;
    state.status = value;
    for (const g of groups.values()) {
      if (g === overdue) continue;
      g.ticket += 1; // a load still in flight answers for the other Status
      g.loading = false;
      g.loaded = false;
      g.held = false;
      g.items = [];
      g.total = 0;
      g.list.classList.remove("stale");
    }
  }

  function pick(slug) {
    haptic("select");
    state.section = slug;
    state.stay = slug === OVERDUE;
    savePrefs({ section: slug });
    if (slug === OVERDUE) setStatus("todo");
    loadSelected();
    window.scrollTo(0, 0);
    render();
  }

  function toggleDone() {
    if (selected() === OVERDUE) return;
    haptic("select");
    setStatus(state.status === "todo" ? "done" : "todo");
    loadSelected();
    render();
  }

  railToggle.onclick = () => {
    haptic("select");
    state.rail = !state.rail;
    savePrefs({ rail: state.rail });
    render();
  };

  // Without the rail the Section's caption opens the same choice as a menu.
  function openSectionMenu() {
    const slug = selected();
    const items = [];
    if (overdue.section.todo_count > 0 || slug === OVERDUE) {
      items.push({
        icon: "⏰",
        label: "Просрочено",
        note: overdue.section.todo_count,
        tone: "danger",
        on: slug === OVERDUE,
        color: "var(--danger)",
        run: () => pick(OVERDUE),
      });
    }
    for (const section of state.sections) {
      items.push({
        icon: markOf(section),
        label: section.name,
        note: section[state.status + "_count"],
        on: section.slug === slug,
        dim: !section.todo_count,
        color: section.color,
        run: () => pick(section.slug),
      });
    }
    items.push({ sep: true });
    if (slug !== OVERDUE) {
      items.push(
        state.status === "done"
          ? { icon: "↩", label: "Показать «Сделать»", run: toggleDone }
          : { icon: "✓", label: "Готово", tone: "good", run: toggleDone },
      );
    }
    items.push({ icon: "✏️", label: "Правка секций", run: startEditing });
    openMenu(secButton.node, items);
  }

  let searchTimer = 0;
  search.oninput = () => {
    rowActions?.close();
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

  function openSearch() {
    if (state.searchOpen || state.editing) return;
    haptic("select");
    state.searchOpen = true;
    render();
    search.focus();
  }

  function closeSearch() {
    clearTimeout(searchTimer);
    searchTicket += 1; // drop any answer still on its way
    search.value = "";
    state.query = "";
    state.results = null;
    state.searchOpen = false;
  }

  searchButton.onclick = openSearch;
  cancelSearch.onclick = () => {
    closeSearch();
    window.scrollTo(0, 0);
    render();
  };

  function startEditing() {
    if (state.editing) return;
    haptic("select");
    closeSearch();
    state.editing = true;
    window.scrollTo(0, 0);
    render();
  }

  function stopEditing() {
    endDrag(true);
    state.editing = false;
    loadSelected();
    render();
  }

  editDone.onclick = () => {
    haptic("select");
    stopEditing();
  };
  addButton.onclick = () => openForm(null);

  // Esc leaves Search or edit mode, «/» opens Search (the key next to the right Shift, whatever the layout).
  document.addEventListener("keydown", (event) => {
    if (!ctx.isCurrent() || state.overlay || isHalted()) return;
    if (event.key === "Escape") {
      if (!state.searchOpen && !state.editing) return;
      event.preventDefault();
      if (state.searchOpen) cancelSearch.onclick();
      else stopEditing();
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey || /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)) return;
    if (event.key === "/" || (event.code === "Slash" && !event.shiftKey)) {
      event.preventDefault();
      openSearch();
    }
  });

  // --- overlays: the item view and the Section form --------------------------

  // `fresh`: the item was fetched just now, so the view need not ask for it again. `focus`: "due" opens the
  // reminder field, "sections" every Section's chip.
  function openItem(item, { fresh = false, focus = null } = {}) {
    state.overlay = openDetail({
      list: main,
      host: overlay,
      item,
      fresh,
      focus,
      sections: state.sections,
      changed: itemChanged,
      deleted: itemDeleted,
      status: (shown, status, extra) => setItemStatus(shown, status, extra),
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
        settle(); // the answer may come after the form was closed
      },
      closed: overlayClosed,
    });
  }

  function overlayClosed() {
    state.overlay = null;
    settle();
    schedulePoll();
  }

  // Brings the lists in line with the server once nothing is in the way: no overlay and no change still in flight.
  function settle() {
    if (!state.dirty || state.overlay || state.writes) return;
    state.dirty = false;
    refresh();
  }

  // The page's one copy of InSection and Overdue membership; the Overdue half is the server's verdict (item.overdue).
  const fits = (item, g) =>
    g === overdue ? item.overdue : item.status === statusOf(g.slug) && item.sections.some((s) => s.slug === g.slug);

  // A kept List (ADR-019) would bring an Item back as it was before a change made here: it takes the new copy
  // where the Item still belongs and loses it where it does not (`item` null: deleted). The next read of a List
  // adds the Items that moved into it.
  function rekeep(id, item) {
    const lists = [[LISTS.overdue().key, Boolean(item?.overdue)]];
    for (const { slug } of state.sections) {
      const filed = Boolean(item?.sections.some((section) => section.slug === slug));
      for (const status of ["todo", "done"]) lists.push([LISTS.inSection(slug, status).key, filed && item.status === status]);
    }
    for (const [key, stays] of lists) {
      const kept = snapshot(key);
      if (!kept?.items.some((other) => other.id === id)) continue;
      if (stays) keepSnapshot(key, { ...kept, items: kept.items.map((other) => (other.id === id ? item : other)) });
      else keepSnapshot(key, { items: kept.items.filter((other) => other.id !== id), total: Math.max(0, kept.total - 1) });
    }
  }

  // An item keeps its place while it still fits a Section's list and leaves it once not; the refresh that follows
  // brings it into the lists it moved to and corrects the counts.
  function applyChange(updated) {
    localGen += 1;
    rekeep(updated.id, updated);
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
  }

  function itemChanged(updated) {
    applyChange(updated);
    changed();
  }

  function dropItem(id) {
    localGen += 1;
    rekeep(id, null);
    let gone = state.results?.items.find((item) => item.id === id) ?? null;
    for (const g of groups.values()) {
      const at = g.items.findIndex((item) => item.id === id);
      if (at < 0) continue;
      [gone] = g.items.splice(at, 1);
      g.total = Math.max(0, g.total - 1);
      if (g === overdue) g.section.todo_count = g.total;
    }
    if (state.results) {
      const before = state.results.items.length;
      state.results.items = state.results.items.filter((item) => item.id !== id);
      state.results.total -= before - state.results.items.length;
    }
    if (gone) moveCounts(gone, gone.status, null);
  }

  function itemDeleted(id) {
    dropItem(id);
    changed();
  }

  function changed() {
    render();
    state.dirty = true;
    settle();
  }

  // --- a row's actions ---------------------------------------------------------

  // Where an Item sits in the loaded lists, so a change taken back puts it where it was.
  const placesOf = (id) =>
    [...groups.values()].map((g) => [g, g.items.findIndex((item) => item.id === id)]).filter(([, at]) => at >= 0);

  function putBack(item, places) {
    for (const [g, at] of places) {
      if (groups.get(g.slug) !== g || !fits(item, g) || g.items.some((other) => other.id === item.id)) continue;
      g.items.splice(Math.min(at, g.items.length), 0, item);
      g.total += 1;
      if (g === overdue) g.section.todo_count = g.total;
    }
  }

  // The Section counts follow a change at once; `to` null: the Item is gone.
  function moveCounts(item, from, to) {
    for (const { slug } of item.sections) {
      const section = state.sections.find((known) => known.slug === slug);
      if (!section) continue;
      section[from + "_count"] = Math.max(0, (section[from + "_count"] || 0) - 1);
      if (to) section[to + "_count"] = (section[to + "_count"] || 0) + 1;
    }
  }

  // A change is on its way to the server: a list read sent before it would bring the old state back, so every
  // read in flight is dropped and none starts until the answer is in.
  function beginWrite() {
    state.writes += 1;
    localGen += 1;
    sectionsTicket += 1;
    searchTicket += 1;
    clearTimeout(pollTimer);
    for (const g of groups.values()) {
      g.ticket += 1;
      g.loading = false;
      g.list.classList.remove("stale");
    }
  }

  function endWrite() {
    state.writes -= 1;
    state.dirty = true;
    settle();
  }

  // One Status change: `next` shows at once (back at `places` if it returns to a list), the server's item replaces
  // it, and a refusal brings `item` back. Resolves to the server's item, or null.
  async function writeStatus(item, next, body, places) {
    const was = placesOf(item.id);
    applyChange(next);
    putBack(next, places);
    moveCounts(item, item.status, next.status);
    render();
    beginWrite();
    const updated = await attempt(() => api(`/notes/items/${item.id}`, { method: "PATCH", body }));
    if (updated) {
      applyChange(updated);
    } else {
      applyChange(item);
      putBack(item, was);
      moveCounts(item, next.status, item.status);
    }
    render();
    endWrite();
    return updated ?? null;
  }

  // «Готово» and «Вернуть», wherever they are tapped: a real change at once (notes ADR-0010), and for 4 s a button
  // that takes it back with a second one. `extra`: the item view's unsaved text, saved in the same request.
  // Resolves to whether the server took it.
  async function setItemStatus(item, status, extra = {}) {
    if (item.status === status) return false;
    haptic("select");
    const places = placesOf(item.id);
    const next = { ...item, ...extra, status, overdue: status === "todo" && item.overdue };
    const write = writeStatus(item, next, { ...extra, status }, []);
    const undo = async () => {
      const updated = await write;
      if (!updated) return;
      const back = { ...updated, status: item.status, overdue: item.overdue };
      writeStatus(updated, back, { status: item.status }, places);
    };
    if (status === "done") toast("Закрыто", { action: undo, label: "↩ Вернуть" });
    else toast("Возвращено в «Сделать»", { action: undo, label: "Отменить" });
    const taken = Boolean(await write);
    if (taken) haptic("success");
    return taken;
  }

  // The bot replies to the original message within a couple of seconds; the app gets out of the way.
  async function showInChat(item) {
    const shown = await attempt(() => api(`/notes/items/${item.id}/show`, { method: "POST" }));
    if (!shown) return;
    haptic("success");
    tg.close();
  }

  async function reenrich(item) {
    beginWrite();
    const updated = await attempt(() => api(`/notes/items/${item.id}/reenrich`, { method: "POST" }));
    if (updated) {
      applyChange(updated);
      render();
      toast(reenrichToast(item));
    }
    endWrite();
  }

  async function remove(item) {
    if (!(await confirmAction("Удалить эту заметку навсегда?"))) return;
    beginWrite();
    const gone = await attempt(async () => {
      await api(`/notes/items/${item.id}`, { method: "DELETE" });
      return true;
    });
    if (gone) {
      dropItem(item.id);
      render();
      toast("Удалено");
    }
    endWrite();
  }

  rowActions = attachRowActions(listCol, {
    itemOf: (id) => shownItems().find((item) => item.id === id) ?? null,
    open: (item) => openItem(item),
    done: (item) => setItemStatus(item, "done"),
    undone: (item) => setItemStatus(item, "todo"),
    remind: (item) => openItem(item, { focus: "due" }),
    sections: (item) => openItem(item, { focus: "sections" }),
    show: showInChat,
    reenrich,
    remove,
  });

  // --- pending items and coming back to the app --------------------------------

  // Only the pending Items shown are asked about, less often each time; one that settles brings a refresh,
  // since the Classifier may have filed it elsewhere.
  let pollTimer = 0;
  let pollStep = 0;
  let polling = false;
  let localGen = 0; // bumps on each change made here: a poll reply sent before one is stale
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (refreshing || state.overlay || state.writes || drag || !ctx.isCurrent() || isHalted()) return;
    if (document.visibilityState !== "visible") return;
    const pending = shownItems().filter((item) => item.enrichment_status === "pending");
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
      data = await api("/notes/items?" + new URLSearchParams(LISTS.recheck(ids).params));
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
      state.dirty = true;
      settle();
      return;
    }
    for (const g of groups.values()) g.items = g.items.map((item) => back.get(item.id) ?? item);
    if (state.results) state.results.items = state.results.items.map((item) => back.get(item.id) ?? item);
    render();
  }

  // Back in the app after sending something in the chat: show what arrived meanwhile.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !ctx.isCurrent() || drag) return;
    pollStep = 0;
    state.dirty = true;
    settle(); // waits for a nested screen to close
  });

  // --- drag and drop (edit mode) ---------------------------------------------

  let drag = null;
  let orderSaving = false;

  function startDrag(g, event) {
    if (!state.editing || drag || orderSaving || state.sections.length < 2) return;
    event.preventDefault();
    const nodes = [...groupsBox.children];
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
    groupsBox.classList.add("sorting");
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
    groupsBox.classList.remove("sorting");
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

  // --- the view --------------------------------------------------------------

  // Once the Sections are known (kept from the last launch), the view shows at once and the refresh runs behind it.
  async function show(arg = {}) {
    state.after = null;
    if (arg.section) {
      // a Section bar on the Dashboard, or «просрочено»: that Section on «Сделать», nothing hiding it
      closeSearch();
      state.editing = false;
      state.section = arg.section;
      state.stay = arg.section === OVERDUE;
      savePrefs({ section: arg.section });
      setStatus("todo");
    }
    // the chat's 📅 asks for one Item: it is fetched alongside the lists, never after them
    const wanted = arg.itemId ? attempt(() => api(`/notes/items/${arg.itemId}`)) : null;
    const loading = refresh();
    const known = arg.section === OVERDUE || state.sections.some((section) => section.slug === arg.section);
    if (!state.sections.length || (arg.section && !known)) await loading; // the Section to show must exist first
    if (wanted) {
      const item = await wanted;
      if (item) state.after = () => openItem(item, { fresh: true });
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
    rowActions.close();
    endDrag(true);
    state.overlay?.close();
    state.editing = false; // the title row belongs to the next view: no way back to «Готово» from there
  }

  return { show, shown, hide };
}
