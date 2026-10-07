// The Section form: create, edit, delete (Other cannot be deleted, ADR-0002).

import { api, attempt, confirmAction, el, haptic, setBack, toast } from "./core.js";
import { OTHER } from "./cards.js";

const DEFAULT_COLOR = "#8a8a8a";

function labelled(box, label, type, value, attrs = {}) {
  const wrap = el("label", "field-label");
  wrap.append(el("span", "hint", label));
  const input = type === "textarea" ? el("textarea", "textarea") : el("input", "input");
  if (type !== "textarea") input.type = type;
  input.value = value;
  Object.assign(input, attrs);
  wrap.append(input);
  box.append(wrap);
  return input;
}

// Grows a textarea to its text, so a long hint reads without scrolling inside the box.
function fitHeight(area) {
  const y = window.scrollY; // the "auto" reset shortens the page for a moment and would move it
  area.style.height = "auto";
  area.style.height = `${area.scrollHeight + area.offsetHeight - area.clientHeight}px`;
  window.scrollTo(0, y);
}

// Shows the form for `section` (null: a new one) in `host` instead of `list`. saved() runs when a change lands,
// closed() when the form goes away. Returns { close }.
export function openSectionForm({ list, host, section, saved, closed }) {
  const listScroll = window.scrollY;
  let busy = false;
  let open = true;

  function close() {
    if (!open) return;
    open = false;
    host.hidden = true;
    host.replaceChildren();
    list.hidden = false;
    setBack(null);
    window.scrollTo(0, listScroll);
    closed();
  }

  async function act(fn) {
    if (busy) return undefined;
    busy = true;
    box.classList.add("busy");
    try {
      return await attempt(fn);
    } finally {
      busy = false;
      box.classList.remove("busy");
    }
  }

  const back = el("button", "btn small ghost", "← Назад");
  back.onclick = close;
  const box = el("article", "detail");
  box.append(el("h2", "title", section ? "Изменить секцию" : "Новая секция"));
  const name = labelled(box, "Название", "text", section?.name ?? "", { name: "name", maxLength: 40 });
  // The server counts characters; this is only a loose bound (UTF-16 units overcount emoji).
  const emoji = labelled(box, "Эмодзи", "text", section?.emoji ?? "", { name: "emoji", maxLength: 32 });
  const color = labelled(box, "Цвет", "color", section?.color ?? DEFAULT_COLOR, { name: "color" });
  const hint = labelled(box, "Подсказка для разбора: что сюда относится", "textarea", section?.hint ?? "", {
    name: "hint",
    maxLength: 500,
    rows: 3,
  });
  hint.oninput = () => fitHeight(hint);

  const actions = el("div", "actions");
  const save = el("button", "btn", "Сохранить");
  save.onclick = async () => {
    const body = { name: name.value, emoji: emoji.value, color: color.value, hint: hint.value };
    const done = await act(() =>
      section
        ? api(`/notes/sections/${section.id}`, { method: "PATCH", body })
        : api("/notes/sections", { method: "POST", body }),
    );
    if (!done) return;
    haptic("success");
    toast(section ? "Сохранено" : "Секция создана");
    saved();
    close();
  };
  actions.append(save);

  if (section && section.slug !== OTHER) {
    const remove = el("button", "btn danger", "Удалить");
    remove.onclick = async () => {
      const question = `Удалить секцию «${section.name}»? Заметки, у которых она единственная, уйдут в «Остальное».`;
      if (!(await confirmAction(question))) return;
      const gone = await act(async () => {
        await api(`/notes/sections/${section.id}`, { method: "DELETE" });
        return true;
      });
      if (!gone) return;
      toast("Удалено");
      saved();
      close();
    };
    actions.append(remove);
  } else if (section) {
    box.append(el("div", "hint", "Сюда попадает всё, что не подошло другим секциям, поэтому её нельзя удалить."));
  }
  box.append(actions);

  host.replaceChildren(back, box);
  list.hidden = true;
  host.hidden = false;
  fitHeight(hint);
  setBack(close);
  window.scrollTo(0, 0);
  return { close };
}
