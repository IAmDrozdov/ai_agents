// Дашборд: todo headline, two day heatmaps on one scale, Section bars. Only a Section bar and «просрочено» are tappable.

import { AuthError, api, attempt, el, handleError, keepSnapshot, setText, slot, snapshot } from "./core.js";

const SVG = "http://www.w3.org/2000/svg";
const CELL = 11;
const GAP = 2;
const PITCH = CELL + GAP;
const LEFT = 20; // room for the weekday labels
const TOP = 12; // room for the month labels
const WEEKDAYS = [[0, "Пн"], [2, "Ср"], [4, "Пт"]]; // prettier-ignore
const EMPTY_HINT = "Пока пусто. Кинь боту ссылку или заметку.";

export const TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

export const parseDay = (iso) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
};
export const isoDay = (date) => date.toISOString().slice(0, 10);
export const addDays = (iso, n) => {
  const date = parseDay(iso);
  date.setUTCDate(date.getUTCDate() + n);
  return isoDay(date);
};

export function fmtDay(iso) {
  return parseDay(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" }).replace(".", "");
}

const monthOf = (iso) =>
  parseDay(iso).toLocaleDateString("ru-RU", { month: "short", timeZone: "UTC" }).replace(".", "");

function svgNode(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  if (text != null) node.textContent = text;
  return node;
}

// One scale for both heatmaps: 0, then four steps up to the larger of the two maxima.
function levelOf(n, max) {
  if (!n || !max) return 0;
  return Math.max(1, Math.ceil((4 * n) / max));
}

function heatmap(series, board, max, field) {
  return dayMap({
    from: board.from,
    to: board.to,
    cls: `heat ${field}`,
    classOf: (day) => `l${levelOf(series[day] || 0, max)}`,
    titleOf: (day) => `${fmtDay(day)}: ${series[day] || 0}`,
  });
}

// A day grid, one column per week from `from` (a Monday) to `to`; days before `first` are left out.
// Every cell carries data-day; classOf(day) adds to its class, titleOf(day) is its tooltip.
export function dayMap({ from, to, first = from, cls, classOf, titleOf }) {
  const weeks = Math.floor((parseDay(to) - parseDay(from)) / (7 * 86400000)) + 1;
  const width = LEFT + weeks * PITCH - GAP;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${TOP + 7 * PITCH - GAP}`, class: cls, role: "img" });
  for (const [row, label] of WEEKDAYS) {
    svg.append(svgNode("text", { x: 0, y: TOP + row * PITCH + CELL - 2, class: "heat-label" }, label));
  }
  let lastMonth = "";
  for (let week = 0; week < weeks; week += 1) {
    const monday = addDays(from, week * 7);
    const month = monthOf(monday < first ? first : monday);
    if (month !== lastMonth) {
      lastMonth = month;
      // a label this close to the right edge would be cut off
      const crowded = week === 0 && monthOf(addDays(from, 7)) !== month; // the next column starts a month
      if (weeks - week >= 3 && !crowded) svg.append(svgNode("text", { x: LEFT + week * PITCH, y: 8, class: "heat-label" }, month));
    }
    for (let row = 0; row < 7; row += 1) {
      const day = addDays(monday, row);
      if (day > to) break;
      if (day < first) continue;
      const rect = svgNode("rect", {
        x: LEFT + week * PITCH,
        y: TOP + row * PITCH,
        width: CELL,
        height: CELL,
        rx: 2,
        class: `cell ${classOf(day)}`,
        "data-day": day,
      });
      rect.append(svgNode("title", {}, titleOf(day)));
      svg.append(rect);
    }
  }
  return svg;
}

// Returns { node, update(board, sections) }; onSection(slug) runs when a Section bar is tapped, onOverdue() on «просрочено».
function buildDashboard(onSection, onOverdue) {
  const node = el("div", "board");

  const headline = el("div", "headline");
  const headNumber = el("span", "headline-n");
  const overdueButton = el("button", "headline-overdue");
  overdueButton.onclick = onOverdue;
  headline.append(headNumber, el("span", "headline-label", "Сделать"), overdueButton);

  const hint = el("p", "empty");
  hint.hidden = true;
  const captured = el("section", "box");
  const done = el("section", "box");
  const bars = el("section", "box");
  for (const [box, title] of [[captured, "Добавлено"], [done, "Готово"], [bars, "Секции"]]) { // prettier-ignore
    box.append(el("h3", null, title), el("div", "box-body"));
  }
  node.append(headline, hint, captured, done, bars);
  const bodyOf = (box) => box.lastChild;

  function update(board, sections) {
    setText(headNumber, String(board.todo));
    overdueButton.hidden = !board.overdue;
    setText(overdueButton, `просрочено: ${board.overdue}`);
    const max = Math.max(0, ...Object.values(board.captured), ...Object.values(board.done));
    const shown = sections.filter((section) => section.todo_count > 0).sort((a, b) => b.todo_count - a.todo_count);
    hint.textContent = EMPTY_HINT;
    hint.hidden = !(board.todo === 0 && max === 0 && !shown.length);

    for (const [box, field] of [[captured, "captured"], [done, "done"]]) {
      slot(bodyOf(box), JSON.stringify([board.from, board.to, max, board[field]]), () => [
        heatmap(board[field], board, max, field),
      ]);
    }

    bars.hidden = !shown.length;
    const top = shown.length ? shown[0].todo_count : 1;
    slot(bodyOf(bars), JSON.stringify(shown.map((s) => [s.slug, s.emoji, s.name, s.color, s.todo_count])), () =>
      shown.map((section) => {
        const row = el("button", "bar-row");
        row.style.setProperty("--chip", section.color);
        const fill = el("span", "bar-fill");
        fill.style.width = `${Math.max(4, Math.round((100 * section.todo_count) / top))}%`;
        const track = el("span", "bar-track");
        track.append(fill);
        row.append(el("span", "bar-label", `${section.emoji} ${section.name}`.trim()), track, el("span", "bar-n", String(section.todo_count)));
        row.onclick = () => onSection(section.slug);
        return row;
      }),
    );
  }

  return { node, update };
}

// Tells the server the Owner's zone without drawing anything: a launch opens whatever the Owner left on (ADR-021).
// Only a lost session is shown: the view on screen reports a dead network itself.
export async function reportZone() {
  try {
    await api("/notes/dashboard?" + new URLSearchParams({ tz: TIMEZONE }));
  } catch (error) {
    if (error instanceof AuthError) handleError(error);
  }
}

// ctx.openSection(slug) opens the list on that Section, ctx.openOverdue() on «Просрочено»; ctx.isCurrent() is false while another view shows.
// Returns { show, hide }; show reloads the figures.
export async function mountDashboard(root, ctx) {
  const dash = buildDashboard(ctx.openSection, ctx.openOverdue);
  root.replaceChildren(dash.node);
  let ticket = 0; // a slower, older reply must not overwrite a newer one

  // Paints the last launch's figures at once when there are any, then the fresh ones.
  async function show() {
    const mine = ++ticket;
    const kept = [snapshot("dashboard"), snapshot("sections")];
    if (kept[0] && kept[1]) dash.update(kept[0], kept[1].sections);
    const fresh = Promise.all([
      attempt(() => api("/notes/dashboard?" + new URLSearchParams({ tz: TIMEZONE }))),
      attempt(() => api("/notes/sections")),
    ]).then(([board, sections]) => {
      if (!board || !sections || mine !== ticket) return;
      keepSnapshot("dashboard", board);
      keepSnapshot("sections", sections);
      dash.update(board, sections.sections);
    });
    if (!kept[0] || !kept[1]) await fresh;
  }

  // Back in the app after sending something in the chat: the figures move.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && ctx.isCurrent()) show();
  });

  return { show, hide() {} };
}
