// Расходы: totals, per-user spend and job history (phone port of the retired dashboard).
// A filter tap only flips classes and swaps the history rows; nothing above them is rebuilt.

import { api, attempt, el, parseTs, plural, reconcile, setText } from "./core.js";

const AGENT_LABELS = { doc_translator: "📄 перевод", pdf_tts: "🔊 аудио", yt_dub: "🎬 озвучка" };
const STATUS_BADGES = {
  ok: ["ok", "✓ готово"],
  error: ["err", "✕ ошибка"],
  running: ["run", "⟳ идёт"],
  interrupted: ["run", "⏹ прервано"],
};
const SORTS = [
  ["new", "Сначала новые"],
  ["cost", "Сначала дорогие"],
  ["slow", "Сначала долгие"],
];
const HISTORY_LIMIT = 200;
const DAYS = 14;
const SVG = "http://www.w3.org/2000/svg";

const fmtInt = (n) => (n == null ? "—" : Number(n).toLocaleString("ru-RU"));
const fmtCost = (n) => (n == null ? "—" : "$" + Number(n).toFixed(4));
const fmtDur = (n) => (n == null ? "—" : Number(n).toFixed(1) + " с");
const fmtKb = (n) => (n == null ? "—" : (n / 1024).toFixed(0) + " КБ");
const jobTokens = (job) => (job.input_tokens || 0) + (job.output_tokens || 0);
const userLabel = (row) => (row.username ? "@" + row.username : "id " + row.telegram_id);

function relTime(ts) {
  const date = parseTs(ts);
  if (!date) return "—";
  const s = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (s < 60) return "только что";
  if (s < 3600) return Math.round(s / 60) + " мин назад";
  if (s < 86400) return Math.round(s / 3600) + " ч назад";
  return Math.round(s / 86400) + " д назад";
}

// The server sums cost per UTC day; this lays out the last `count` days, empty ones at zero.
function dailyCost(daily, count) {
  const now = new Date();
  const base = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const spent = Object.fromEntries(daily.map((row) => [row.day, row.cost_usd]));
  const days = [];
  for (let i = count - 1; i >= 0; i--) {
    const iso = new Date(base - i * 86400000).toISOString();
    days.push({ label: iso.slice(5, 10), v: spent[iso.slice(0, 10)] || 0 });
  }
  return days;
}

// Scales down with its tile (viewBox, no fixed size) so two tiles always fit a narrow phone.
function sparkline(days) {
  const W = 150;
  const H = 34;
  const PAD = 4;
  const max = Math.max(...days.map((day) => day.v), 1e-9);
  const step = days.length > 1 ? (W - 2 * PAD) / (days.length - 1) : 0;
  const points = days.map((day, i) => [PAD + i * step, H - 3 - (H - 8) * (day.v / max)]);
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `расходы по дням, последние ${days.length} дн.`);
  const line = document.createElementNS(SVG, "polyline");
  line.setAttribute("class", "spark-line");
  line.setAttribute("points", points.map((p) => p.map((x) => x.toFixed(1)).join(",")).join(" "));
  const last = points[points.length - 1];
  const dot = document.createElementNS(SVG, "circle");
  dot.setAttribute("class", "spark-dot");
  dot.setAttribute("cx", last[0].toFixed(1));
  dot.setAttribute("cy", last[1].toFixed(1));
  dot.setAttribute("r", "3");
  const title = document.createElementNS(SVG, "title");
  title.textContent = days.map((day) => `${day.label}: $${day.v.toFixed(4)}`).join("\n");
  svg.append(line, dot, title);
  return svg;
}

function tile(label, value, sub, extra) {
  const node = el("div", "tile");
  node.append(el("div", "label", label), el("div", "value", value));
  if (extra) node.append(extra);
  node.append(el("div", "sub", sub));
  return node;
}

function jobDetails(job) {
  const box = el("div", "details");
  box.hidden = true;
  const facts =
    `файл ${fmtKb(job.file_size_bytes)} → результат ${fmtKb(job.output_size_bytes)} · ` +
    `символов ${fmtInt(job.char_count)}` +
    (job.tts_chars_billed ? ` · озвучено ${fmtInt(job.tts_chars_billed)}` : "") +
    ` · завершено ${job.finished_at || "—"}`;
  box.append(el("div", "hint", facts));
  if (job.error) box.append(el("div", "error", "Ошибка: " + job.error));
  if (job.config_json) box.append(el("pre", null, "config " + JSON.stringify(job.config_json, null, 1)));
  if (job.stats_json) box.append(el("pre", null, "stats  " + JSON.stringify(job.stats_json, null, 1)));
  return box;
}

function jobCard(job) {
  const node = el("article", "job");
  const [cls, label] = STATUS_BADGES[job.status] || ["run", job.status];
  const head = el("div", "job-head");
  head.append(el("span", "job-agent", AGENT_LABELS[job.agent] || job.agent), el("span", "badge " + cls, label));
  const file = el("div", "job-file", job.filename || "—");
  const facts = [userLabel(job), relTime(job.created_at)];
  if (jobTokens(job)) facts.push(fmtInt(jobTokens(job)) + " ток.");
  if (job.cost_usd != null) facts.push(fmtCost(job.cost_usd));
  if (job.duration_s != null) facts.push(fmtDur(job.duration_s));
  node.append(head, file, el("div", "hint", facts.join(" · ")));
  const details = jobDetails(job);
  node.append(details);
  node.onclick = () => {
    details.hidden = !details.hidden;
  };
  return node;
}

export async function mountUsage(root) {
  const state = { user: null, status: null, sort: "new" };
  let data = null;
  const jobNodes = new Map(); // job id -> card, so an expanded job stays expanded across filters
  const userRows = new Map(); // telegram id -> row

  const toolbar = el("div", "toolbar");
  const refresh = el("button", "btn small ghost", "↻ Обновить");
  toolbar.append(el("h1", null, "Расходы бота"), refresh);
  const kpis = el("section", "kpis");
  const users = el("section", "block");
  const history = el("section", "block");
  const historyTitle = el("h2", "grow", "История");
  const sort = el("select", "select");
  sort.name = "sort";
  sort.setAttribute("aria-label", "Сортировка");
  for (const [value, label] of SORTS) {
    const option = el("option", null, label);
    option.value = value;
    sort.append(option);
  }
  sort.onchange = () => {
    state.sort = sort.value;
    renderHistory();
  };
  const historyHead = el("div", "toolbar");
  historyHead.append(historyTitle, sort);
  const rows = el("div");
  history.append(historyHead, rows);

  let errorTile = null;
  let errorSub = null;

  function buildKpis() {
    const t = data.totals;
    const tokens = data.by_user.reduce((sum, u) => sum + u.tokens, 0);
    const cost = tile("Всего потрачено", "$" + (t.cost_usd || 0), `по дням, ${DAYS} дн.`, sparkline(dailyCost(data.daily, DAYS)));
    const jobs = tile("Задачи", fmtInt(t.jobs), `${t.ok_jobs || 0} ок · ${t.error_jobs || 0} с ошибкой`);
    const tok = tile("Токены", fmtInt(tokens), "перевод: вход + выход");
    const rate = t.jobs ? (100 * (t.error_jobs || 0)) / t.jobs : 0;
    errorTile = tile("Ошибки", rate.toFixed(1) + "%", "");
    errorSub = errorTile.querySelector(".sub");
    errorTile.classList.add("clickable");
    errorTile.onclick = () => {
      state.status = state.status === "error" ? null : "error";
      syncFilters();
      renderHistory();
    };
    kpis.replaceChildren(cost, jobs, tok, errorTile);
  }

  function buildUsers() {
    userRows.clear();
    users.replaceChildren(el("h2", null, "По пользователям"));
    if (!data.by_user.length) {
      users.append(el("p", "empty", "Пока нет задач."));
      return;
    }
    for (const u of data.by_user) {
      const row = el("button", "user-row");
      const jobs = `${fmtInt(u.jobs)} ${plural(u.jobs, "задача", "задачи", "задач")}`;
      row.append(el("span", "user-name", userLabel(u)), el("span", "hint", `${jobs} · ${fmtInt(u.tokens)} ток.`), el("span", "user-cost", "$" + u.cost_usd.toFixed(4)));
      row.onclick = () => {
        state.user = state.user === u.telegram_id ? null : u.telegram_id;
        syncFilters();
        renderHistory();
      };
      userRows.set(u.telegram_id, row);
      users.append(row);
    }
  }

  // Highlights what is filtered; a tap on the highlighted tile or row clears it.
  function syncFilters() {
    const errorsOnly = state.status === "error";
    errorTile.classList.toggle("on", errorsOnly);
    setText(errorSub, errorsOnly ? "сбросить фильтр" : "показать ошибки"); // same width, so the tile never reflows
    for (const [id, row] of userRows) row.classList.toggle("on", state.user === id);
  }

  function renderHistory() {
    sort.value = state.sort;
    const parts = ["История"];
    if (state.user != null) {
      const u = data.by_user.find((row) => row.telegram_id === state.user);
      parts.push(u ? userLabel(u) : String(state.user));
    }
    if (state.status != null) parts.push("ошибки");
    setText(historyTitle, parts.join(" · "));

    let found = data.jobs.slice();
    if (state.user != null) found = found.filter((job) => job.telegram_id === state.user);
    if (state.status != null) found = found.filter((job) => job.status === state.status);
    const keys = { new: (job) => job.id, cost: (job) => job.cost_usd ?? -1, slow: (job) => job.duration_s ?? -1 };
    found.sort((a, b) => keys[state.sort](b) - keys[state.sort](a));
    const nodes = found.map((job) => {
      if (!jobNodes.has(job.id)) jobNodes.set(job.id, jobCard(job));
      return jobNodes.get(job.id);
    });
    if (!nodes.length) nodes.push(el("p", "empty", "Под фильтр ничего не попало."));
    reconcile(rows, nodes);
  }

  async function load() {
    const fresh = await attempt(() => api(`/usage?limit=${HISTORY_LIMIT}`));
    if (!fresh) return false;
    data = fresh;
    jobNodes.clear();
    buildKpis();
    buildUsers();
    syncFilters();
    renderHistory();
    return true;
  }

  refresh.onclick = load;
  if (await load()) {
    root.replaceChildren(toolbar, kpis, users, history);
    return;
  }
  const retry = el("button", "btn wide", "Повторить");
  retry.onclick = () => mountUsage(root);
  root.replaceChildren(el("p", "empty", "Не удалось загрузить расходы."), retry);
}
