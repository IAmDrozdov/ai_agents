// Секции: the list with its order, and the create / edit / delete form.

import { api, attempt, confirmAction, el, haptic, plural, setBack, toast } from "./core.js";

const OTHER = "other";
const DEFAULT_COLOR = "#8a8a8a";

function labelled(box, label, type, value, attrs = {}) {
  const wrap = el("label", "field-label");
  wrap.append(el("span", "hint", label));
  const input = el("input", "input");
  input.type = type;
  input.value = value;
  Object.assign(input, attrs);
  wrap.append(input);
  box.append(wrap);
  return input;
}

export async function mountSections(root) {
  setBack(null);
  const state = { sections: [], busy: false, listScroll: 0, gen: 0 }; // gen: bumps on a local change
  const listView = el("div");
  const formView = el("div");
  formView.hidden = true;
  root.replaceChildren(listView, formView);

  // One request at a time: a second tap would be built from a list the first is about to replace.
  async function act(fn) {
    if (state.busy) return undefined;
    state.busy = true;
    root.classList.add("busy");
    try {
      return await attempt(fn);
    } finally {
      state.busy = false;
      root.classList.remove("busy");
    }
  }

  async function load() {
    const gen = state.gen;
    const data = await attempt(() => api("/notes/sections"));
    if (gen !== state.gen) return; // something changed here after this request went out: that wins
    if (data) state.sections = data.sections;
    renderList();
  }

  // The list changes at once; the server's answer confirms it, or the old order comes back.
  async function move(index, delta) {
    if (state.busy) return;
    const before = state.sections;
    const next = [...before];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    haptic("select");
    state.gen += 1;
    state.sections = next;
    renderList();
    const done = await act(() =>
      api("/notes/sections/order", { method: "PUT", body: { ids: next.map((section) => section.id) } }),
    );
    if (done) return;
    state.sections = before;
    renderList();
    await load();
  }

  function row(section, index) {
    const node = el("article", "section-row");
    const swatch = el("span", "swatch");
    swatch.style.setProperty("--chip", section.color);
    const body = el("div", "section-body");
    body.append(el("div", "title", `${section.emoji} ${section.name}`.trim()));
    const count = `${section.todo_count} ${plural(section.todo_count, "запись", "записи", "записей")}`;
    body.append(el("div", "hint", [section.hint, count].filter(Boolean).join(" · ")));

    const actions = el("div", "row-actions");
    const button = (label, aria, handler, disabled = false) => {
      const b = el("button", "btn small ghost", label);
      b.setAttribute("aria-label", aria);
      b.disabled = disabled;
      b.onclick = handler;
      actions.append(b);
    };
    button("▲", "Выше", () => move(index, -1), index === 0);
    button("▼", "Ниже", () => move(index, 1), index === state.sections.length - 1);
    button("✎", "Изменить", () => openForm(section));
    node.append(swatch, body, actions);
    return node;
  }

  function renderList() {
    const toolbar = el("div", "toolbar");
    const add = el("button", "btn small", "+ Новая секция");
    add.onclick = () => openForm(null);
    toolbar.append(el("h1", null, "Секции"), add);
    const rows = state.sections.map(row);
    if (!rows.length) rows.push(el("p", "empty", "Секций нет."));
    listView.replaceChildren(toolbar, ...rows);
  }

  // --- form ----------------------------------------------------------------

  function showList() {
    formView.hidden = true;
    listView.hidden = false;
    setBack(null);
    window.scrollTo(0, state.listScroll);
  }

  // After a change the list is corrected from the server's answer, then checked against the server (counts).
  function changed(sections) {
    state.gen += 1;
    state.sections = sections;
    renderList();
    showList();
    load();
  }

  function openForm(section) {
    state.listScroll = window.scrollY;
    listView.hidden = true;
    formView.hidden = false;
    setBack(showList);
    window.scrollTo(0, 0);

    const back = el("button", "btn small ghost", "← К секциям");
    back.onclick = showList;
    const box = el("article", "detail");
    box.append(el("h2", "title", section ? "Изменить секцию" : "Новая секция"));
    const name = labelled(box, "Название", "text", section?.name ?? "", { name: "name", maxLength: 40 });
    // The server counts characters; this is only a loose bound (UTF-16 units overcount emoji).
    const emoji = labelled(box, "Эмодзи", "text", section?.emoji ?? "", { name: "emoji", maxLength: 32 });
    const color = labelled(box, "Цвет", "color", section?.color ?? DEFAULT_COLOR, { name: "color" });
    const hint = labelled(box, "Подсказка для разбора: что сюда относится", "text", section?.hint ?? "", {
      name: "hint",
      maxLength: 200,
    });

    const actions = el("div", "actions");
    const save = el("button", "btn", "Сохранить");
    save.onclick = async () => {
      const body = { name: name.value, emoji: emoji.value, color: color.value, hint: hint.value };
      const saved = await act(() =>
        section
          ? api(`/notes/sections/${section.id}`, { method: "PATCH", body })
          : api("/notes/sections", { method: "POST", body }),
      );
      if (!saved) return;
      haptic("success");
      toast(section ? "Сохранено" : "Секция создана");
      if (section) {
        changed(state.sections.map((s) => (s.id === saved.id ? { ...s, ...saved } : s)));
        return;
      }
      const next = [...state.sections];
      const at = next.findIndex((s) => s.slug === OTHER);
      next.splice(at < 0 ? next.length : at, 0, { ...saved, todo_count: 0 });
      changed(next);
    };
    actions.append(save);

    if (section && section.slug !== OTHER) {
      const remove = el("button", "btn danger", "Удалить");
      remove.onclick = async () => {
        const question = `Удалить секцию «${section.name}»? Записи, у которых она единственная, уйдут в «Остальное».`;
        if (!(await confirmAction(question))) return;
        const gone = await act(async () => {
          await api(`/notes/sections/${section.id}`, { method: "DELETE" });
          return true;
        });
        if (!gone) return;
        toast("Удалено");
        changed(state.sections.filter((s) => s.id !== section.id));
      };
      actions.append(remove);
    } else if (section) {
      box.append(el("div", "hint", "Сюда попадает всё, что не подошло другим секциям, поэтому её нельзя удалить."));
    }
    box.append(actions);
    formView.replaceChildren(back, box);
  }

  await load();
}
