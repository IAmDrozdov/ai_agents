// Дневник · записи: today's Day editor at the root (ADR-021), and nested under it the Week (seven Days with Marks,
// Entries and the Week's Summary), another Day's editor, and the Month and Year screens where Entries are raised
// further. Vocabulary: apps/diary/CONTEXT.md; rules: ADR-020.

import {
  api,
  attempt,
  el,
  handleError,
  haptic,
  keepSnapshot,
  plural,
  resetSlot,
  setBack,
  slot,
  snapshot,
  tg,
  toast,
} from "./core.js";
import { TIMEZONE, addDays, fmtDay, parseDay } from "./dashboard.js";

export const MARK_EMOJI = { dead: "💀", meh: "😐", fire: "🔥" };
const MARK_NAMES = { dead: "Плохой день", meh: "Обычный день", fire: "Отличный день" };
const MARKS = ["dead", "meh", "fire"];
const LEVELS = ["day", "week", "month", "year"];
const LEVEL_LABEL = { week: "неделя", month: "месяц", year: "год" };
const MAX_TEXT = 120;
const COUNTER_FROM = 100; // the remaining length shows from here on
export const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]; // prettier-ignore

const pad = (n) => String(n).padStart(2, "0");

// What differs between the Month and the Year screens (ADR-020 decision 3).
const PERIODS = {
  month: {
    own: "Итоги месяца",
    from: "Из итогов недель",
    none: "В итогах недель этого месяца ничего нет.",
    summary: ["month", "year"],
    candidate: "week",
    path: (p) => "/diary/month?" + new URLSearchParams({ year: p.year, month: p.month }),
    title: (p) => `${MONTHS[p.month - 1]} ${p.year}`,
    shift: (p, by) => {
      const index = p.year * 12 + p.month - 1 + by;
      return { year: Math.floor(index / 12), month: (index % 12) + 1 };
    },
  },
  year: {
    own: "Итоги года",
    from: "Из итогов месяцев",
    none: "В итогах месяцев этого года ничего нет.",
    summary: ["year"],
    candidate: "month",
    path: (p) => "/diary/year?" + new URLSearchParams({ year: p.year }),
    title: (p) => String(p.year),
    shift: (p, by) => ({ year: p.year + by }),
  },
};

// The Owner's local date; the server is told the same zone (`tz`).
export function todayIso() {
  const now = new Date();
  return [now.getFullYear(), pad(now.getMonth() + 1), pad(now.getDate())].join("-");
}

export const mondayOf = (iso) => addDays(iso, -((parseDay(iso).getUTCDay() + 6) % 7));
const weekdayOf = (iso) => parseDay(iso).toLocaleDateString("ru-RU", { weekday: "short", timeZone: "UTC" });
const longDay = (iso) =>
  capital(parseDay(iso).toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }));
const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const stepOf = (level, by) => LEVELS[LEVELS.indexOf(level) + by];

// A keyboard at hand: the «Что сделано» field takes the focus by itself. On a phone that would raise the keyboard.
const wantsFocus = () => matchMedia("(pointer: fine)").matches || ["macos", "tdesktop"].includes(tg.platform);

// [] at day Level, so it spreads into a row.
function levelTag(level) {
  return level === "day" ? [] : [el("span", "level-tag", LEVEL_LABEL[level])];
}

// One Entry in a Summary or a candidate list: its Day, its text, its Level, one step button.
function summaryRow(entry, symbol, onStep) {
  const row = el("div", "entry-row");
  const text = el("span", "entry-text", entry.text);
  const day = el("span", "entry-day", fmtDay(entry.day));
  const button = el("button", "step", symbol);
  button.setAttribute("aria-label", symbol === "+" ? "Поднять" : "Опустить");
  button.onclick = () => onStep(entry);
  row.append(day, text, ...levelTag(entry.level), button);
  return row;
}

// ctx.isCurrent() is false while another view shows; ctx.setBar() sets this view's part of the title row.
// Returns { show(arg), shown(), hide() }; arg: { day } opens that Day's Week over today's editor.
export async function mountToday(root, ctx) {
  const state = {
    rootDay: todayIso(), // the Day the root editor is for
    now: null, // the current Week, { start, days, summary }: what the root editor and the week line read
    anchor: todayIso(), // any Day of the Week on the Week screen
    today: todayIso(), // «today» when the Week was last read: once the Day turns, the current Week follows it
    week: null, // the Week on the Week screen; the same object as `now` while that is the current one
    top: snapshot("diary-top") ?? [], // the five most frequent Entry texts
    screens: [], // the open Week / Day editor / Month / Year, the top one last
    after: null, // what shown() does once the pane is on screen
  };
  let rootEditor = null;
  let todayTicket = 0;
  let ticket = 0;
  let writes = Promise.resolve(); // writes go one at a time, so their answers land in the order they were made
  let pending = 0; // writes not yet answered: a read meanwhile could undo one on screen
  let written = 0; // writes answered so far: a read that began before one of them is as old
  let missed = false; // a read was dropped, or a write failed: everything on screen is read again after the writes
  let todayRead = null; // the current Week on its way, for a Week screen that wants the same one
  const levels = new Map(); // Entry id -> { level } shown and not yet answered: it stays over a Day that lands first
  let shows = 0;

  const main = el("div", "diary-today"); // the root: today's editor and the week line
  const host = el("div");
  host.hidden = true;
  root.replaceChildren(main, host);

  const line = el("button", "week-line");
  const lineText = document.createTextNode("");
  line.append(lineText, el("span", null, "›"));
  line.onclick = () => openWeek(todayIso());
  const weekButton = el("button", "btn small ghost", "Неделя ›");
  weekButton.onclick = () => openWeek(todayIso());
  ctx.setBar({ right: [weekButton] });

  const weekNode = el("div");
  const nav = el("div", "diary-nav");
  const prev = el("button", "btn small ghost", "‹");
  const title = el("h2", "diary-title");
  const next = el("button", "btn small ghost", "›");
  prev.setAttribute("aria-label", "Предыдущая неделя");
  next.setAttribute("aria-label", "Следующая неделя");
  nav.append(prev, title, next);
  const months = el("div", "chip-row diary-months");
  const days = el("div", "diary-days");
  const summary = el("section", "box");
  summary.append(el("h3", null, "Итоги недели"), el("div", "diary-list"));
  const summaryBody = summary.lastChild;
  weekNode.append(nav, months, days, summary);
  const weekScreen = { node: weekNode, reload: loadWeek };

  prev.onclick = () => moveWeek(-7);
  next.onclick = () => moveWeek(7);

  // --- writes --------------------------------------------------------------------------------

  // Queues one write and applies its answer; a failure reloads what is true, once every write is in.
  function write(send, apply) {
    pending += 1;
    writes = writes
      .then(send)
      .then(apply)
      .catch((error) => {
        missed = true;
        handleError(error);
      })
      .finally(() => {
        pending -= 1;
        written += 1;
        if (pending || !missed) return;
        missed = false;
        loadToday();
        for (const screen of state.screens) screen.reload?.();
      });
    return writes;
  }

  // True for an answer that may predate a write: one is still out (everything is read again after it), or one
  // landed since the read began at `mark` (then `again` asks anew).
  function crossed(mark, again) {
    if (pending) missed = true;
    else if (mark !== written) again();
    else return false;
    return true;
  }

  // The Weeks in memory, each once: the current one and the one on the Week screen.
  const weeks = () => [...new Set([state.now, state.week])].filter(Boolean);
  // Every Day editor alive: the root's and any open over the Week.
  const editors = () => [rootEditor, ...state.screens].filter(Boolean);

  // A Day as the server now has it: into the Weeks that hold it, and into every editor of it.
  function takeDay(day) {
    for (const entry of day.entries) if (levels.has(entry.id)) entry.level = levels.get(entry.id).level;
    for (const week of weeks()) {
      const at = week.days.findIndex((d) => d.day === day.day);
      if (at < 0) continue;
      week.days[at] = day;
      resummarise(week);
    }
    keepWeek();
    paintWeek();
    paintLine();
    for (const screen of editors()) screen.takeDay?.(day);
  }

  function resummarise(week) {
    week.summary = week.days.flatMap((d) => d.entries.filter((e) => e.level !== "day").map((e) => ({ ...e, day: d.day })));
  }

  function setLevel(entryId, level) {
    for (const week of weeks()) {
      for (const d of week.days) for (const e of d.entries) if (e.id === entryId) e.level = level;
      resummarise(week);
    }
    keepWeek();
    paintWeek();
    for (const screen of editors()) screen.setLevel?.(entryId, level);
  }

  // «+» / «−»: the Level changes on screen at once, then the server's answer settles it.
  function step(entry, by, onDone) {
    const level = stepOf(entry.level, by);
    if (!level) return;
    haptic("select");
    setLevel(entry.id, level);
    const shown = { level };
    levels.set(entry.id, shown);
    const settled = () => {
      if (levels.get(entry.id) === shown) levels.delete(entry.id); // a later step on the same Entry keeps its own
    };
    onDone?.({ ...entry, level });
    write(
      () =>
        api(`/diary/entries/${entry.id}/${by > 0 ? "raise" : "lower"}`, { method: "POST" }).catch((error) => {
          settled();
          throw error;
        }),
      (answer) => {
        settled();
        if (levels.has(entry.id)) return; // a later step on this Entry is still out: its answer settles it
        setLevel(answer.id, answer.level);
        onDone?.(answer);
      },
    );
  }

  function refreshTop() {
    attempt(() => api("/diary/suggestions")).then((top) => {
      if (!top) return;
      state.top = top;
      keepSnapshot("diary-top", top);
      for (const screen of editors()) screen.paintTop?.();
    });
  }

  // --- the root: today's Day editor and the week line -------------------------------------------

  // A new editor when the Day turns; what was being typed moves over to it.
  function mountRoot(iso) {
    const typed = rootEditor?.text() ?? "";
    const known = state.now?.days.find((d) => d.day === iso);
    rootEditor = dayEditor(iso, known ? structuredClone(known) : { day: iso, mark: null, entries: [] }, false);
    rootEditor.setText(typed);
    state.rootDay = iso;
    main.replaceChildren(rootEditor.node, line);
  }

  function paintLine() {
    const n = state.now?.days.filter((d) => d.entries.length).length ?? 0;
    line.hidden = !state.now;
    lineText.data = n ? `Эта неделя: ${n} ${plural(n, "день", "дня", "дней")} с записями` : "Эта неделя: пока без записей";
  }

  function paintRoot() {
    const day = state.now?.days.find((d) => d.day === state.rootDay);
    if (day) rootEditor.takeDay(day);
    paintLine();
  }

  function focusRoot() {
    if (wantsFocus()) rootEditor?.focus();
  }

  // Reads the current Week and the top five in one round; the kept Week paints first.
  async function loadToday() {
    const mine = ++todayTicket;
    const today = todayIso();
    const start = mondayOf(today);
    if (state.now?.start !== start) {
      const kept = snapshot("diary-week");
      state.now = kept?.start === start ? kept : null;
    }
    if (!rootEditor || state.rootDay !== today) mountRoot(today);
    paintRoot();
    const mark = written;
    const fresh = Promise.all([
      attempt(() => api("/diary/week?" + new URLSearchParams({ day: today, tz: TIMEZONE }))),
      attempt(() => api("/diary/suggestions")),
    ]).then(([week, top]) => {
      if (top) {
        state.top = top;
        keepSnapshot("diary-top", top);
        for (const screen of editors()) screen.paintTop?.();
      }
      if (!week || mine !== todayTicket || crossed(mark, loadToday)) return;
      if (state.week?.start === week.start) state.week = week;
      state.now = week;
      keepWeek();
      paintWeek();
      paintRoot();
    });
    todayRead = fresh;
    fresh.finally(() => {
      if (todayRead === fresh) todayRead = null;
    });
    if (!state.now) await fresh;
  }

  // --- the Week ------------------------------------------------------------------------------

  function keepWeek() {
    if (state.now?.start === mondayOf(todayIso())) keepSnapshot("diary-week", state.now);
  }

  function paintWeek() {
    const start = mondayOf(state.anchor);
    const end = addDays(start, 6);
    title.textContent = `${fmtDay(start)} – ${fmtDay(end)}`;
    const covered = [...new Set([start, end].map((d) => d.slice(0, 7)))];
    slot(months, covered.join(), () =>
      covered.map((ym) => {
        const [y, m] = ym.split("-").map(Number);
        const chip = el("button", "chip filter", `${MONTHS[m - 1]} →`);
        chip.onclick = () => openMonth(y, m);
        return chip;
      }),
    );
    const week = state.week?.start === start ? state.week : null;
    const today = todayIso();
    slot(days, JSON.stringify([week?.days ?? start, today]), () =>
      (week?.days ?? []).map((d) => dayCard(d, d.day === today, d.day > today)),
    );
    summary.hidden = !week;
    slot(summaryBody, JSON.stringify(week?.summary ?? []), () =>
      week?.summary.length
        ? week.summary.map((e) => summaryRow(e, "−", (entry) => step(entry, -1)))
        : [el("p", "hint", "Нажми «+» у записи, чтобы поднять её в итоги недели.")],
    );
  }

  function dayCard(day, isToday, future) {
    const card = el("div", "day-card" + (isToday ? " today" : "") + (future ? " future" : ""));
    const head = el("button", "day-head");
    head.append(
      el("span", "day-name", `${capital(weekdayOf(day.day))}, ${fmtDay(day.day)}`),
      el("span", "day-mark", MARK_EMOJI[day.mark] ?? ""),
    );
    head.onclick = () => openDay(day.day);
    card.append(head);
    for (const entry of day.entries) {
      const row = el("div", "entry-row");
      const text = el("span", "entry-text", entry.text);
      text.onclick = () => openDay(day.day);
      row.append(text);
      if (entry.level === "day") {
        const raise = el("button", "step", "+");
        raise.setAttribute("aria-label", "В итоги недели");
        raise.onclick = () => step({ ...entry, day: day.day }, 1);
        row.append(raise);
      } else {
        row.append(...levelTag(entry.level), el("span", "step-spacer"));
      }
      card.append(row);
    }
    return card;
  }

  // Reads the Week on the Week screen; the current Week paints first from what the root already holds.
  async function loadWeek() {
    const mine = ++ticket;
    state.today = todayIso();
    const start = mondayOf(state.anchor);
    if (state.week?.start !== start) state.week = state.now?.start === start ? state.now : null;
    paintWeek();
    if (todayRead && start === mondayOf(state.today)) {
      // today's editor is reading this very Week: its answer serves both
      if (state.week) return;
      await todayRead;
      if (mine !== ticket) return;
      if (state.now?.start === start) {
        state.week = state.now;
        paintWeek();
        return;
      }
    }
    const mark = written;
    const asked = "/diary/week?" + new URLSearchParams({ day: state.anchor, tz: TIMEZONE });
    const fresh = attempt(() => api(asked)).then((week) => {
      if (!week || mine !== ticket || crossed(mark, loadWeek)) return;
      state.week = week;
      if (week.start === mondayOf(todayIso())) {
        state.now = week;
        keepWeek();
        paintRoot();
      }
      paintWeek();
    });
    if (!state.week) await fresh;
  }

  function moveWeek(by) {
    state.anchor = addDays(mondayOf(state.anchor), by);
    loadWeek();
  }

  // --- nested screens: the Week, a Day editor, the Month, the Year ---------------------------

  function push(screen) {
    (state.screens.at(-1)?.node ?? main).hidden = true;
    state.screens.push(screen);
    screen.node.hidden = false; // the Week's node is used again after a screen over it was dropped
    host.append(screen.node);
    host.hidden = false;
    setBack(pop);
    window.scrollTo(0, 0);
  }

  function pop() {
    const screen = state.screens.pop();
    if (!screen) return;
    screen.node.remove();
    const below = state.screens.at(-1);
    if (below) {
      below.node.hidden = false;
      below.reload?.();
    } else {
      host.hidden = true;
      main.hidden = false;
      setBack(null);
      loadToday(); // the screens above may have changed today's Entries
      focusRoot();
    }
    window.scrollTo(0, 0);
  }

  function closeAll() {
    while (state.screens.length) state.screens.pop().node.remove();
    host.hidden = true;
    main.hidden = false;
    setBack(null);
  }

  // «Неделя ›», the week line, a Day on the Dashboard: that Day's Week, straight over the root.
  function openWeek(day) {
    closeAll();
    state.anchor = day;
    push(weekScreen);
    loadWeek();
  }

  function openDay(iso) {
    const known = state.week?.days.find((d) => d.day === iso);
    push(dayEditor(iso, known ? structuredClone(known) : { day: iso, mark: null, entries: [] }, !known));
  }

  function dayEditor(iso, initial, unknown) {
    let day = initial;
    let local = []; // changes shown and not yet answered: each stays over any Day that lands before its own answer
    const node = el("div", "detail diary-editor");
    const head = el("h2", null, longDay(iso));
    const markRow = el("div", "mark-row");
    const markButtons = MARKS.map((mark) => {
      const button = el("button", "mark-btn", MARK_EMOJI[mark]);
      button.setAttribute("aria-label", MARK_NAMES[mark]);
      button.title = MARK_NAMES[mark];
      button.onclick = () => setMark(day.mark === mark ? null : mark);
      markRow.append(button);
      return button;
    });

    const form = el("form", "add-row");
    const input = el("input", "input");
    Object.assign(input, { type: "text", maxLength: MAX_TEXT, placeholder: "Что сделано", autocomplete: "off" });
    input.enterKeyHint = "done";
    const addButton = el("button", "btn", "Добавить");
    addButton.type = "submit";
    form.append(input, addButton);
    const counter = el("p", "hint counter");
    const suggest = el("div", "chip-row suggest");
    const list = el("div", "diary-list");
    node.append(head, markRow, form, counter, suggest, list);

    form.onsubmit = (event) => {
      event.preventDefault();
      add(input.value);
    };
    let typed = 0;
    input.oninput = () => {
      paintCounter();
      clearTimeout(typed);
      typed = setTimeout(paintSuggest, 150);
    };

    const found = new Map(); // prefix -> texts
    let suggestTicket = 0;
    async function paintSuggest() {
      const prefix = input.value.trim();
      if (!prefix) {
        slot(suggest, "top:" + state.top.join("\n"), () => state.top.map((text) => suggestion(text)));
        return;
      }
      const mine = ++suggestTicket;
      if (!found.has(prefix)) {
        const texts = await attempt(() => api("/diary/suggestions?" + new URLSearchParams({ prefix, limit: 8 })));
        if (!texts) return;
        found.set(prefix, texts);
      }
      if (mine !== suggestTicket) return;
      const texts = found.get(prefix).filter((t) => t !== prefix);
      slot(suggest, "q:" + texts.join("\n"), () => texts.map((text) => suggestion(text)));
    }

    function suggestion(text) {
      const chip = el("button", "chip filter", text);
      chip.type = "button";
      chip.onclick = () => add(text);
      return chip;
    }

    function paintCounter() {
      const left = MAX_TEXT - input.value.length;
      counter.textContent = `осталось ${left}`;
      counter.style.visibility = input.value.length >= COUNTER_FROM ? "visible" : "hidden"; // keeps its room
    }

    function paint() {
      markButtons.forEach((button, i) => button.classList.toggle("on", day.mark === MARKS[i]));
      slot(list, JSON.stringify(day.entries), () =>
        day.entries.length ? day.entries.map(entryRow) : [el("p", "hint", "Записей нет.")],
      );
    }

    // «+» raises the Entry into the Week's Summary; a raised one shows its Level instead. Deleting is inside «✏️».
    function entryRow(entry) {
      const row = el("div", "entry-row" + (entry.id < 0 ? " pending" : ""));
      const text = el("span", "entry-text", entry.text);
      const raise = el("button", "step", "+");
      raise.setAttribute("aria-label", "В итоги недели");
      raise.onclick = () => step({ ...entry, day: iso }, 1);
      const edit = el("button", "step", "✏️");
      edit.setAttribute("aria-label", "Изменить");
      edit.onclick = () => row.replaceWith(editRow(entry));
      row.append(text, ...(entry.level === "day" ? [raise] : levelTag(entry.level)), edit);
      if (entry.id < 0) raise.disabled = edit.disabled = true;
      return row;
    }

    function editRow(entry) {
      const row = el("form", "add-row");
      const field = el("input", "input");
      Object.assign(field, { type: "text", maxLength: MAX_TEXT, value: entry.text, autocomplete: "off" });
      const save = el("button", "btn small", "OK");
      save.type = "submit";
      const cancel = el("button", "btn small ghost", "✕");
      cancel.type = "button";
      cancel.setAttribute("aria-label", "Отмена");
      cancel.onclick = () => {
        resetSlot(list);
        paint();
      };
      row.onsubmit = (event) => {
        event.preventDefault();
        const text = field.value.trim();
        if (!text) return toast("Пустая запись");
        resetSlot(list);
        change(
          (d) => ({ ...d, entries: d.entries.map((e) => (e.id === entry.id ? { ...e, text } : e)) }),
          () => api(`/diary/entries/${entry.id}`, { method: "PATCH", body: { text } }),
          refreshTop,
        );
      };
      const remove = el("button", "btn small danger", "🗑");
      remove.type = "button";
      remove.setAttribute("aria-label", "Удалить");
      remove.onclick = () => {
        resetSlot(list);
        removeEntry(entry);
      };
      row.append(field, save, cancel, remove);
      setTimeout(() => field.focus(), 0);
      return row;
    }

    // One change to the Day: `op` (Day -> Day) shows at once, the request follows, and its answer is the Day.
    function change(op, send, then) {
      const drop = () => {
        local = local.filter((o) => o !== op);
      };
      local.push(op);
      day = op(day);
      paint();
      write(
        () =>
          send().catch((error) => {
            drop();
            throw error;
          }),
        (answer) => {
          drop();
          takeDay(answer);
          then?.();
        },
      );
    }

    let temp = 0;
    function add(raw) {
      const text = raw.trim();
      if (!text) return;
      input.value = "";
      paintCounter();
      paintSuggest();
      haptic("select");
      const entry = { id: --temp, text, level: "day" };
      change(
        (d) => ({ ...d, entries: [...d.entries, entry] }),
        () => api("/diary/entries", { method: "POST", body: { day: iso, text } }),
        refreshTop,
      );
    }

    function removeEntry(entry) {
      change(
        (d) => ({ ...d, entries: d.entries.filter((e) => e.id !== entry.id) }),
        () => api(`/diary/entries/${entry.id}`, { method: "DELETE" }),
      );
    }

    function setMark(mark) {
      haptic("select");
      change(
        (d) => ({ ...d, mark }),
        () => api("/diary/marks", { method: "PUT", body: { day: iso, mark } }),
      );
    }

    async function reload() {
      const mark = written;
      const week = await attempt(() => api("/diary/week?" + new URLSearchParams({ day: iso })));
      const fresh = week?.days.find((d) => d.day === iso);
      if (fresh && !crossed(mark, reload)) screen.takeDay(fresh);
    }

    const screen = {
      node,
      reload,
      takeDay(answer) {
        if (answer.day !== iso) return;
        // the Week keeps its own copy: an Entry not yet saved shows only here
        day = local.reduce((d, op) => op(d), structuredClone(answer));
        paint();
      },
      setLevel(entryId, level) {
        day.entries = day.entries.map((e) => (e.id === entryId ? { ...e, level } : e));
        paint();
      },
      paintTop: () => input.value.trim() || paintSuggest(),
      focus: () => input.focus(),
      text: () => input.value,
      setText(value) {
        input.value = value;
        paintCounter();
        paintSuggest();
      },
    };
    paint();
    paintCounter();
    paintSuggest();
    if (unknown) reload();
    return screen;
  }

  // A Month or a Year: its Summary with «−», and the Entries one Level below with «+».
  function summaryScreen(kind, period) {
    const spec = PERIODS[kind];
    const node = el("div", "diary-period");
    const nav = el("div", "diary-nav");
    const back = el("button", "btn small ghost", "‹");
    back.setAttribute("aria-label", "Назад");
    const head = el("h2", "diary-title");
    const fwd = el("button", "btn small ghost", "›");
    fwd.setAttribute("aria-label", "Вперёд");
    nav.append(back, head, fwd);
    const up = el("button", "chip filter");
    const ownBox = el("section", "box");
    ownBox.append(el("h3", null, spec.own), el("div", "diary-list"));
    const candBox = el("section", "box");
    candBox.append(el("h3", null, spec.from), el("div", "diary-list"));
    node.append(nav, ...(kind === "month" ? [up] : []), ownBox, candBox);
    const ownList = ownBox.lastChild;
    const candList = candBox.lastChild;
    let data = null; // { summary, candidates }
    let mine = 0;

    function paint() {
      head.textContent = spec.title(period);
      up.textContent = `Итоги ${period.year} года →`;
      const rows = (entries, symbol, by, empty) =>
        entries.length ? entries.map((e) => summaryRow(e, symbol, (entry) => move(entry, by))) : [el("p", "hint", empty)];
      slot(ownList, JSON.stringify(data?.summary ?? null), () =>
        rows(data?.summary ?? [], "−", -1, data ? "Пока пусто: подними запись снизу «+»." : "Загрузка…"),
      );
      slot(candList, JSON.stringify(data?.candidates ?? null), () =>
        rows(data?.candidates ?? [], "+", 1, data ? spec.none : ""),
      );
    }

    // An Entry's new Level puts it in the Summary or among the candidates; one from another period is ignored.
    function place(entry) {
      const all = data ? [...data.summary, ...data.candidates] : [];
      if (!all.some((e) => e.id === entry.id)) return;
      const moved = all.map((e) => (e.id === entry.id ? { ...e, level: entry.level } : e));
      moved.sort((a, b) => (a.day === b.day ? a.id - b.id : a.day < b.day ? -1 : 1));
      data = {
        summary: moved.filter((e) => spec.summary.includes(e.level)),
        candidates: moved.filter((e) => e.level === spec.candidate),
      };
      paint();
    }

    function move(entry, by) {
      if (data) step(entry, by, place);
    }

    async function reload() {
      const asked = ++mine;
      const mark = written;
      const fresh = await attempt(() => api(spec.path(period)));
      if (!fresh || asked !== mine || crossed(mark, reload)) return;
      data = fresh;
      paint();
    }

    function shift(by) {
      period = spec.shift(period, by);
      data = null;
      paint();
      reload();
    }
    back.onclick = () => shift(-1);
    fwd.onclick = () => shift(1);
    up.onclick = () => push(summaryScreen("year", { year: period.year }));

    paint();
    reload();
    return { node, reload };
  }

  function openMonth(year, month) {
    push(summaryScreen("month", { year, month }));
  }

  // --- the view ------------------------------------------------------------------------------

  async function show(arg = {}) {
    const mine = ++shows;
    state.after = null;
    if (arg.day) {
      // a Day on the Dashboard: its Week, both read before the pane is swapped in
      closeAll();
      state.anchor = arg.day;
      await Promise.all([loadToday(), loadWeek()]);
      if (mine !== shows) return;
      state.after = () => push(weekScreen); // the back button belongs to the pane on screen: it waits for shown()
    } else {
      await loadToday();
    }
  }

  function shown() {
    const after = state.after;
    state.after = null;
    if (after) after();
    else if (!state.screens.length) focusRoot();
  }

  // Back in the app after a while: the Day may have turned, and the editor and the current Week with it.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !ctx.isCurrent()) return;
    const top = state.screens.at(-1);
    if (!top) {
      loadToday();
    } else if (top === weekScreen) {
      if (mondayOf(state.anchor) === mondayOf(state.today)) state.anchor = todayIso();
      loadWeek();
    }
  });

  return { show, shown, hide: closeAll };
}
