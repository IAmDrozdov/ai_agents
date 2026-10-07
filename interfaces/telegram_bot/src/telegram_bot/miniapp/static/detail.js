// The item view: opens over any list, edits one item, and reports every change back to the list that opened it.

import {
  AuthError,
  api,
  attempt,
  confirmAction,
  el,
  handleError,
  haptic,
  isHalted,
  setBack,
  setText,
  slot,
  tg,
  toast,
} from "./core.js";
import {
  OTHER,
  enrichmentBadge,
  externalLink,
  fmtDate,
  fmtDue,
  fmtDuration,
  isHttp,
  itemTitle,
  originOf,
  sectionLabel,
  toLocalInput,
} from "./cards.js";

const PENDING_POLL_MS = 3000;
// The item fields the top of the item view shows; it is rebuilt only when one of them changes.
const HEAD_FIELDS = [
  "kind", "url", "title", "text", "source", "author", "gist", "file_name",
  "created_at", "enrichment_status", "enrichment_error", "caption",
  "transcript", "sender", "duration_s", "tg_message_id",
]; // prettier-ignore

// Shows `item` in `host` instead of `list`. hooks: sections (all, in order), changed(item), deleted(id), closed(),
// visible() (false once the tab is left). Returns { close }.
export function openDetail({ list, host, item, ...hooks }) {
  const state = {
    detail: item,
    open: true,
    rev: 0, // bumps when the Owner starts a change, so an older copy fetched in the background is dropped
    busy: false,
    draft: null, // unsaved text
    dueOpen: false, // «+» was tapped and no Due is saved yet
  };
  let pollTimer = 0;
  const listScroll = window.scrollY;
  const parts = build();
  sync(item);
  list.hidden = true;
  host.hidden = false;
  setBack(close);
  window.scrollTo(0, 0);
  document.addEventListener("visibilitychange", onReturn);
  freshen();

  function close() {
    if (!state.open) return;
    state.open = false;
    clearTimeout(pollTimer);
    document.removeEventListener("visibilitychange", onReturn);
    host.hidden = true;
    host.replaceChildren();
    list.hidden = false;
    setBack(null);
    window.scrollTo(0, listScroll);
    hooks.closed();
  }

  // Quietly picks up anything newer than the copy on screen.
  async function freshen() {
    if (state.busy) return; // a reply sent before the change lands could undo it on screen
    const rev = state.rev;
    let fresh;
    try {
      fresh = await api(`/notes/items/${state.detail.id}`);
    } catch (error) {
      if (error instanceof AuthError) handleError(error); // anything else: the copy already on screen will do
      return;
    }
    if (!state.open || rev !== state.rev || state.busy) return;
    if (JSON.stringify(fresh) !== JSON.stringify(state.detail)) {
      state.detail = fresh;
      sync(fresh);
      hooks.changed(fresh);
    }
  }

  // Enrichment settles within seconds: while the item is still pending, check back quietly.
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!state.open || !hooks.visible() || isHalted() || document.visibilityState !== "visible") return;
    if (state.detail.enrichment_status === "pending") {
      pollTimer = setTimeout(async () => {
        await freshen();
        schedulePoll();
      }, PENDING_POLL_MS);
    }
  }

  function onReturn() {
    if (document.visibilityState === "visible") schedulePoll();
  }

  // One change at a time: a second tap would be built from state the first one is about to replace.
  async function act(fn) {
    if (state.busy) return undefined;
    state.busy = true;
    parts.box.classList.add("busy"); // the card, not the whole view: "← К списку" stays tappable
    try {
      return await attempt(fn);
    } finally {
      state.busy = false;
      parts.box.classList.remove("busy");
    }
  }

  // `preview` is shown at once and dropped if the server says no; the server's item then replaces it.
  async function patch(body, preview = {}) {
    if (state.busy) return null;
    const before = state.detail;
    state.rev += 1;
    sync({ ...before, ...preview });
    const updated = await act(() => api(`/notes/items/${before.id}`, { method: "PATCH", body }));
    if (!updated) {
      if (state.open) sync(before);
      return null;
    }
    hooks.changed(updated);
    if (!state.open) return updated;
    state.detail = updated;
    if ("text" in body && parts.area.value === body.text) state.draft = null; // else typing went on meanwhile
    sync(updated);
    haptic("success");
    return updated;
  }

  function build() {
    const back = el("button", "btn small ghost", "← К списку");
    back.onclick = close;
    const box = el("article", "detail");
    const head = el("div", "stack");

    const sectionRow = el("div", "chip-row");
    const sectionButtons = new Map();
    for (const section of hooks.sections) {
      const chip = el("button", "chip filter", sectionLabel(section));
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

    // One row of fixed height holds «+», or the input with «×»: opening it moves nothing.
    const dueRow = el("div", "due-row");
    const dueAdd = el("button", "btn small ghost", "+ Напомнить");
    dueAdd.onclick = openDue;
    const dueInput = el("input", "input due-input");
    dueInput.type = "datetime-local";
    dueInput.name = "due";
    dueInput.onchange = () => moveDue(dueInput.value);
    const dueClear = el("button", "btn small ghost", "×");
    dueClear.setAttribute("aria-label", "Убрать напоминание");
    dueClear.onclick = removeDue;
    dueRow.append(dueAdd, dueInput, dueClear);

    box.append(head, el("h3", null, "Секции"), sectionRow, el("h3", null, "Напоминание"), dueRow, noteTitle, field, actions);
    host.replaceChildren(back, box);
    return { box, head, sectionButtons, noteTitle, area, save, actions, dueAdd, dueInput, dueClear };
  }

  async function toggleSection(slug) {
    if (state.busy) return;
    haptic("select");
    const next = new Set(state.detail.sections.map((section) => section.slug));
    const wasOn = next.delete(slug);
    if (!wasOn) next.add(slug);
    const lastOne = wasOn && !next.size && slug !== OTHER;
    const preview = { sections: hooks.sections.filter((section) => next.has(section.slug)) };
    const updated = await patch({ sections: [...next] }, preview);
    if (updated && lastOne) toast("Перенёс в «Остальное»");
  }

  function openDue() {
    if (state.busy) return;
    haptic("select");
    state.dueOpen = true;
    sync(state.detail);
    parts.dueInput.min = toLocalInput(new Date());
    parts.dueInput.focus();
    try {
      parts.dueInput.showPicker?.();
    } catch {
      // a browser without a picker still takes typing
    }
  }

  async function moveDue(value) {
    const when = value ? new Date(value) : null;
    if (!when || Number.isNaN(when.getTime())) {
      sync(state.detail);
      return;
    }
    if (when.getTime() <= Date.now()) {
      toast("Это время уже прошло");
      sync(state.detail);
      return;
    }
    const due = when.toISOString();
    const updated = await patch({ due }, { due_at: due });
    if (updated) toast("⏰ " + fmtDue(updated.due_at));
  }

  async function removeDue() {
    if (state.busy) return;
    haptic("select");
    state.dueOpen = false;
    if (state.detail.due_at) await patch({ due: null }, { due_at: null, reminded_at: null });
    else sync(state.detail);
  }

  async function reenrich() {
    if (state.busy) return;
    const id = state.detail.id;
    const slugs = state.detail.sections.map((section) => section.slug);
    const refiles = !slugs.length || (slugs.length === 1 && slugs[0] === OTHER); // the Classifier's rule (ADR-0010)
    state.rev += 1;
    const updated = await act(() => api(`/notes/items/${id}/reenrich`, { method: "POST" }));
    if (!updated) return;
    hooks.changed(updated);
    if (!state.open) return;
    state.detail = updated;
    sync(updated);
    toast(refiles ? "Поставил в очередь" : "Поставил в очередь. Секции оставлю как есть");
  }

  async function deleteForever() {
    if (state.busy || !(await confirmAction("Удалить эту заметку навсегда?"))) return;
    const id = state.detail.id;
    state.rev += 1;
    const gone = await act(async () => {
      await api(`/notes/items/${id}`, { method: "DELETE" });
      return true;
    });
    if (!gone) return;
    toast("Удалено");
    hooks.deleted(id);
    close();
  }

  // The bot replies to the original message within a couple of seconds; the app gets out of the way.
  async function showInChat() {
    if (state.busy) return;
    const shown = await act(() => api(`/notes/items/${state.detail.id}/show`, { method: "POST" }));
    if (!shown) return;
    haptic("success");
    tg.close();
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

  // Brings the view in line with `item`: only what differs is touched.
  function sync(item) {
    const { head, sectionButtons, noteTitle, area, save, actions, dueAdd, dueInput, dueClear } = parts;
    slot(head, JSON.stringify(HEAD_FIELDS.map((field) => item[field])), () => headNodes(item));
    const current = new Set(item.sections.map((section) => section.slug));
    for (const [slug, button] of sectionButtons) button.classList.toggle("on", current.has(slug));
    setText(noteTitle, item.kind === "note" ? "Текст заметки" : "Моя пометка");
    const saved = item.text || "";
    if (state.draft == null && area.value !== saved) area.value = saved;
    save.disabled = area.value === saved;
    const dueShown = Boolean(item.due_at) || state.dueOpen;
    dueAdd.hidden = dueShown;
    dueInput.hidden = !dueShown;
    dueClear.hidden = !dueShown;
    dueInput.value = item.due_at ? toLocalInput(item.due_at) : "";
    slot(actions, item.status, () => actionNodes(item));
    schedulePoll();
  }

  return { close };
}
