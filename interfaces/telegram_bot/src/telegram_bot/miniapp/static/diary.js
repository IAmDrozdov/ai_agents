// Записи: the Week (seven Days with Marks, Entries and the Week's Summary), the Day editor, and the Month and Year
// screens where Entries are raised further. Vocabulary: apps/diary/CONTEXT.md; rules: ADR-020.

import { api, attempt, el, handleError, haptic, keepSnapshot, resetSlot, setBack, slot, snapshot, toast } from "./core.js";
import { TIMEZONE, addDays, fmtDay, parseDay } from "./dashboard.js";

export const MARK_EMOJI = { dead: "💀", meh: "😐", fire: "🔥" };
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

// «Добавить запись» on both sides of the diary's toggle: today's Day editor.
export function addEntryButton(ctx) {
  const button = el("button", "btn wide diary-add", "+ Добавить запись");
  button.onclick = () => ctx.open("week", { edit: todayIso() });
  return button;
}

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

// ctx.open(view, arg) switches the toggle; ctx.isCurrent() is false while another tab or view shows.
// Returns { show(arg), shown(), hide() }; arg: { day } opens that Day's Week, { edit: day } its Day editor too.
export async function mountWeek(root, ctx) {
  const state = {
    anchor: todayIso(), // any Day of the Week on screen
    today: todayIso(), // «today» when the Week was last read: once the Day turns, the current Week follows it
    week: null, // { start, days, summary } as last read or written
    top: snapshot("diary-top") ?? [], // the five most frequent Entry texts
    screens: [], // the open Day editor / Month / Year, the top one last
    after: null, // what shown() does once the pane is on screen
  };
  let ticket = 0;
  let writes = Promise.resolve(); // writes go one at a time, so their answers land in the order they were made
  let pending = 0; // writes not yet answered: a read meanwhile could undo one on screen

  const main = el("div");
  const host = el("div");
  host.hidden = true;
  root.replaceChildren(main, host);

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
  main.append(addEntryButton(ctx), nav, months, days, summary);

  prev.onclick = () => moveWeek(-7);
  next.onclick = () => moveWeek(7);

  // --- writes --------------------------------------------------------------------------------

  // Queues one write and applies its answer; a failure reloads what is true.
  function write(send, apply) {
    pending += 1;
    let failed = false;
    writes = writes
      .then(send)
      .then(apply)
      .catch((error) => {
        failed = true;
        handleError(error);
      })
      .finally(() => {
        pending -= 1;
        if (!failed) return;
        loadWeek();
        for (const screen of state.screens) screen.reload?.();
      });
    return writes;
  }

  // A Day as the server now has it: into the Week if it is on screen, and into an open editor of it.
  function takeDay(day) {
    if (state.week) {
      const at = state.week.days.findIndex((d) => d.day === day.day);
      if (at >= 0) {
        state.week.days[at] = day;
        resummarise();
        keepWeek();
        paintWeek();
      }
    }
    for (const screen of state.screens) screen.takeDay?.(day);
  }

  function resummarise() {
    state.week.summary = state.week.days.flatMap((d) =>
      d.entries.filter((e) => e.level !== "day").map((e) => ({ ...e, day: d.day })),
    );
  }

  function setLevel(entryId, level) {
    for (const d of state.week?.days ?? []) for (const e of d.entries) if (e.id === entryId) e.level = level;
    if (state.week) {
      resummarise();
      keepWeek();
      paintWeek();
    }
  }

  // «+» / «−»: the Level changes on screen at once, then the server's answer settles it.
  function step(entry, by, onDone) {
    const level = stepOf(entry.level, by);
    if (!level) return;
    haptic("select");
    setLevel(entry.id, level);
    onDone?.({ ...entry, level });
    write(
      () => api(`/diary/entries/${entry.id}/${by > 0 ? "raise" : "lower"}`, { method: "POST" }),
      (answer) => {
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
      for (const screen of state.screens) screen.paintTop?.();
    });
  }

  // --- the Week ------------------------------------------------------------------------------


  function keepWeek() {
    if (state.week && state.week.start === mondayOf(todayIso())) keepSnapshot("diary-week", state.week);
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

  // Reads the Week on screen and the top five in one round; the kept current Week paints first.
  async function loadWeek() {
    const mine = ++ticket;
    state.today = todayIso();
    const start = mondayOf(state.anchor);
    if (state.week?.start !== start) {
      const kept = snapshot("diary-week");
      state.week = kept?.start === start ? kept : null;
    }
    paintWeek();
    const fresh = Promise.all([
      attempt(() => api("/diary/week?" + new URLSearchParams({ day: state.anchor, tz: TIMEZONE }))),
      attempt(() => api("/diary/suggestions")),
    ]).then(([week, top]) => {
      if (top) {
        state.top = top;
        keepSnapshot("diary-top", top);
      }
      if (!week || mine !== ticket || pending) return;
      state.week = week;
      keepWeek();
      paintWeek();
    });
    if (!state.week) await fresh;
  }

  function moveWeek(by) {
    state.anchor = addDays(mondayOf(state.anchor), by);
    loadWeek();
  }

  // --- screens over the Week: the Day editor, the Month, the Year ---------------------------

  function push(screen) {
    (state.screens.at(-1)?.node ?? main).hidden = true;
    state.screens.push(screen);
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
      loadWeek(); // a Month or Year screen may have moved Entries of this Week
    }
    window.scrollTo(0, 0);
  }

  function closeAll() {
    while (state.screens.length) state.screens.pop().node.remove();
    host.hidden = true;
    main.hidden = false;
    setBack(null);
  }

  function openDay(iso) {
    const known = state.week?.days.find((d) => d.day === iso);
    push(dayEditor(iso, known ? structuredClone(known) : { day: iso, mark: null, entries: [] }, !known));
  }

  function dayEditor(iso, initial, unknown) {
    let day = initial;
    const node = el("div", "detail diary-editor");
    const head = el("h2", null, longDay(iso));
    const markRow = el("div", "mark-row");
    const markButtons = MARKS.map((mark) => {
      const button = el("button", "mark-btn", MARK_EMOJI[mark]);
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

    function entryRow(entry) {
      const row = el("div", "entry-row" + (entry.id < 0 ? " pending" : ""));
      const text = el("span", "entry-text", entry.text);
      const edit = el("button", "step", "✏️");
      edit.setAttribute("aria-label", "Изменить");
      edit.onclick = () => row.replaceWith(editRow(entry));
      const remove = el("button", "step", "🗑");
      remove.setAttribute("aria-label", "Удалить");
      remove.onclick = () => removeEntry(entry);
      row.append(text, ...levelTag(entry.level), edit, remove);
      if (entry.id < 0) edit.disabled = remove.disabled = true;
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
      cancel.onclick = () => {
        resetSlot(list);
        paint();
      };
      row.onsubmit = (event) => {
        event.preventDefault();
        const text = field.value.trim();
        if (!text) return toast("Пустая запись");
        day.entries = day.entries.map((e) => (e.id === entry.id ? { ...e, text } : e));
        resetSlot(list);
        paint();
        write(
          () => api(`/diary/entries/${entry.id}`, { method: "PATCH", body: { text } }),
          (answer) => {
            takeDay(answer);
            refreshTop();
          },
        );
      };
      row.append(field, save, cancel);
      setTimeout(() => field.focus(), 0);
      return row;
    }

    let temp = 0;
    function add(raw) {
      const text = raw.trim();
      if (!text) return;
      input.value = "";
      paintCounter();
      paintSuggest();
      haptic("select");
      day.entries = [...day.entries, { id: --temp, text, level: "day" }];
      paint();
      write(
        () => api("/diary/entries", { method: "POST", body: { day: iso, text } }),
        (answer) => {
          takeDay(answer);
          refreshTop();
        },
      );
    }

    function removeEntry(entry) {
      day.entries = day.entries.filter((e) => e.id !== entry.id);
      paint();
      write(() => api(`/diary/entries/${entry.id}`, { method: "DELETE" }), takeDay);
    }

    function setMark(mark) {
      haptic("select");
      day = { ...day, mark };
      paint();
      write(() => api("/diary/marks", { method: "PUT", body: { day: iso, mark } }), takeDay);
    }

    async function reload() {
      const week = await attempt(() => api("/diary/week?" + new URLSearchParams({ day: iso })));
      const fresh = week?.days.find((d) => d.day === iso);
      if (fresh && !pending) screen.takeDay(fresh);
    }

    const screen = {
      node,
      reload,
      takeDay(answer) {
        if (answer.day !== iso) return;
        day = answer;
        paint();
      },
      paintTop: () => input.value.trim() || paintSuggest(),
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
    const head = el("h2", "diary-title");
    const fwd = el("button", "btn small ghost", "›");
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
      const fresh = await attempt(() => api(spec.path(period)));
      if (!fresh || asked !== mine || pending) return;
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
    state.after = null;
    const wanted = arg.edit ?? arg.day;
    if (wanted) {
      closeAll();
      state.anchor = wanted;
    } else if (!state.screens.length && !state.week) {
      state.anchor = todayIso();
    }
    await loadWeek();
    if (arg.edit) state.after = () => openDay(arg.edit);
  }

  function shown() {
    const after = state.after;
    state.after = null;
    after?.();
  }

  // Back in the app after a while: the Day may have turned, and the current Week with it.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !ctx.isCurrent() || state.screens.length) return;
    if (mondayOf(state.anchor) === mondayOf(state.today)) state.anchor = todayIso();
    loadWeek();
  });

  return { show, shown, hide: closeAll };
}
