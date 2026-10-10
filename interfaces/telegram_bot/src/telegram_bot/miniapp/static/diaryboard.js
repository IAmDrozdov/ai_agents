// Дневник · дашборд: one Year's Day map coloured by Mark, the counts, the most repeated Entry, the best Month.
// A Day on the map opens its Week in «записи».

import { api, attempt, el, keepSnapshot, plural, setText, slot, snapshot } from "./core.js";
import { TIMEZONE, dayMap, fmtDay } from "./dashboard.js";
import { MARK_EMOJI, MONTHS, mondayOf, todayIso } from "./diary.js";

const EMPTY_HINT = "В этом году записей пока нет. Запиши что-нибудь в «Записях» — и день появится на карте.";

// Two half-years, each as wide as a notes heatmap, so a Day stays big enough to tap on a phone.
function markMaps(board) {
  const halves = [
    [`${board.year}-01-01`, `${board.year}-06-30`],
    [`${board.year}-07-01`, `${board.year}-12-31`],
  ];
  return halves.map(([first, to]) =>
    dayMap({
      from: mondayOf(first),
      to,
      first,
      cls: "heat marks",
      classOf: (day) => (board.marks[day] ? `m-${board.marks[day]}` : ""),
      titleOf: (day) => `${fmtDay(day)} ${MARK_EMOJI[board.marks[day]] ?? ""}`.trim(),
    }),
  );
}

function tile(label) {
  const node = el("div", "stat");
  const n = el("span", "stat-n");
  node.append(n, el("span", "stat-label", label));
  return { node, set: (value) => setText(n, String(value)) };
}

// ctx.open(mode, arg) opens the place's other mode; ctx.isCurrent() is false while another view shows.
export async function mountDiaryBoard(root, ctx) {
  const node = el("div", "board");
  const nav = el("div", "diary-nav");
  const prev = el("button", "btn small ghost", "‹");
  const title = el("h2", "diary-title");
  const next = el("button", "btn small ghost", "›");
  prev.setAttribute("aria-label", "Предыдущий год");
  next.setAttribute("aria-label", "Следующий год");
  nav.append(prev, title, next);

  const hint = el("p", "empty", EMPTY_HINT);
  const map = el("section", "box");
  map.append(el("h3", null, "Дни"), el("div", "box-body diary-maps"));
  const mapBody = map.lastChild;
  mapBody.onclick = (event) => {
    const day = event.target.closest?.("[data-day]")?.dataset.day;
    if (day) ctx.open("list", { day });
  };
  const tiles = el("div", "stats");
  const counts = {
    entries: tile("записей"),
    days: tile("дней с записью"),
    streak: tile("серия"),
    fire: tile("🔥 дней"),
  };
  tiles.append(...Object.values(counts).map((s) => s.node));
  const facts = el("section", "box diary-facts");
  const topLine = el("p", "fact");
  const bestLine = el("p", "fact");
  facts.append(topLine, bestLine);
  node.append(nav, hint, map, tiles, facts);
  root.replaceChildren(node);

  const thisYear = () => Number(todayIso().slice(0, 4));
  let year = thisYear();
  let ticket = 0;

  function paint(board) {
    setText(title, String(board.year));
    const empty = !board.entries && !Object.keys(board.marks).length;
    hint.hidden = !empty;
    slot(mapBody, JSON.stringify([board.year, board.marks]), () => markMaps(board));
    counts.entries.set(board.entries);
    counts.days.set(board.days_with_entry);
    counts.streak.set(`${board.streak} ${plural(board.streak, "день", "дня", "дней")}`);
    counts.fire.set(board.fire_days);
    tiles.hidden = empty;
    facts.hidden = empty;
    setText(topLine, board.top_entry ? `Чаще всего: «${board.top_entry.text}» × ${board.top_entry.count}` : "Повторов пока нет");
    setText(bestLine, board.best_month ? `Лучший месяц: ${MONTHS[board.best_month - 1].toLowerCase()}` : "");
  }

  // Paints the kept Dashboard of the current Year at once, then the fresh one.
  async function show() {
    const mine = ++ticket;
    const current = year === thisYear();
    const kept = current ? snapshot("diary-board") : null;
    if (kept?.year === year) paint(kept);
    const fresh = attempt(() => api("/diary/dashboard?" + new URLSearchParams({ year, tz: TIMEZONE }))).then((board) => {
      if (!board || mine !== ticket) return;
      if (current) keepSnapshot("diary-board", board);
      paint(board);
    });
    if (kept?.year !== year) await fresh;
  }

  prev.onclick = () => {
    year -= 1;
    show();
  };
  next.onclick = () => {
    year += 1;
    show();
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && ctx.isCurrent()) show();
  });

  return { show, hide() {} };
}
