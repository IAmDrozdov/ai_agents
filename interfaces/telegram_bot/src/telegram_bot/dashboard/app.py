"""Usage dashboard: single-page client-rendered UI over the bot's sqlite.

Localhost only (SSH tunnel). FastAPI injects one JSON payload; a framework-free
script renders KPI tiles, a per-user table, and a sortable/filterable/expandable
job history. All user-provided strings go through textContent (XSS-safe).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import db

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22><text y=%2214%22 font-size=%2214%22>📊</text></svg>">
<title>ai_agents — usage</title>
<style>
:root {
  color-scheme: light;
  --surface: #fcfcfb; --page: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-3: #898781;
  --border: rgba(11,11,11,0.10); --grid: #e1e0d9; --zebra: rgba(11,11,11,0.03);
  --good: #006300; --good-chip: rgba(12,163,12,0.12); --good-dot: #0ca30c;
  --bad: #d03b3b; --bad-chip: rgba(208,59,59,0.10);
  --accent: #2a78d6; --accent-wash: rgba(42,120,214,0.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
    --border: rgba(255,255,255,0.10); --grid: #2c2c2a; --zebra: rgba(255,255,255,0.04);
    --good: #0ca30c; --good-chip: rgba(12,163,12,0.16); --good-dot: #0ca30c;
    --bad: #e66767; --bad-chip: rgba(230,103,103,0.14);
    --accent: #3987e5; --accent-wash: rgba(57,135,229,0.16);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink-1);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 24px 20px 64px; }
header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 24px; }
h1 { font-size: 21px; font-weight: 600; margin: 0; }
h2 { font-size: 15px; font-weight: 600; margin: 32px 0 8px; }
.meta { color: var(--ink-3); font-size: 12px; margin-left: auto; }
button.refresh {
  font: inherit; font-size: 12px; color: var(--accent); background: none;
  border: 1px solid var(--border); border-radius: 6px; padding: 3px 10px; cursor: pointer;
}
button.refresh:hover { background: var(--accent-wash); }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.tile {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 16px; display: flex; flex-direction: column; gap: 2px;
}
.tile .label { font-size: 12px; color: var(--ink-2); }
.tile .value { font-size: 30px; font-weight: 600; line-height: 1.15; }
.tile .sub { font-size: 12px; color: var(--ink-3); }
.tile.clickable { cursor: pointer; }
.tile.clickable:hover { border-color: var(--accent); }
.tile.active { outline: 2px solid var(--accent); outline-offset: -1px; }
.tile svg { margin-top: 6px; }

.chips { display: flex; gap: 8px; margin: 12px 0 4px; min-height: 24px; align-items: center; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
  background: var(--accent-wash); color: var(--accent);
  border: 1px solid var(--accent); border-radius: 999px; padding: 2px 10px;
}
.chip button { all: unset; cursor: pointer; font-weight: 700; padding: 0 2px; }
.chips .hint { color: var(--ink-3); font-size: 12px; }

table { border-collapse: collapse; width: 100%; background: var(--surface);
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
th, td { padding: 7px 12px; text-align: left; font-size: 13px; }
th { color: var(--ink-2); font-weight: 600; font-size: 12px; border-bottom: 1px solid var(--grid);
     position: sticky; top: 0; background: var(--surface); cursor: pointer; user-select: none;
     white-space: nowrap; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr:nth-child(4n+3), tbody tr:nth-child(4n+4) { background: var(--zebra); }
tbody tr.row { cursor: pointer; }
tbody tr.row:hover { background: var(--accent-wash); }
tr.detail { display: none; }
tr.detail.open { display: table-row; }
tr.detail td { border-top: 1px dashed var(--grid); padding: 10px 16px 14px; }
tr.detail pre {
  margin: 6px 0 0; padding: 10px; font-size: 11.5px; overflow-x: auto;
  background: var(--page); border: 1px solid var(--grid); border-radius: 6px;
}
#users tbody tr { cursor: pointer; }
#users tbody tr:hover { background: var(--accent-wash); }
#users tbody tr:nth-child(even) { background: var(--zebra); }

.badge {
  display: inline-flex; align-items: center; gap: 5px; border-radius: 999px;
  padding: 1px 9px; font-size: 12px; font-weight: 500; white-space: nowrap;
}
.badge.ok { color: var(--good); background: var(--good-chip); border: 1px solid var(--good-dot); }
.badge.err { color: var(--bad); background: var(--bad-chip); border: 1px solid var(--bad); }
.badge.run { color: var(--ink-2); background: var(--zebra); border: 1px solid var(--grid); }

time { border-bottom: 1px dotted var(--ink-3); cursor: help; }
.empty { text-align: center; color: var(--ink-3); padding: 28px 12px; }
.filename { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dim { color: var(--ink-3); }
.sort-ind { color: var(--accent); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>ai_agents — bot usage</h1>
    <span class="meta">updated <span id="updated">just now</span></span>
    <button class="refresh" onclick="location.reload()">↻ Refresh</button>
  </header>

  <section class="kpis" id="kpis"></section>

  <h2>By user <span class="dim" style="font-weight:400">— click a row to filter the history</span></h2>
  <table id="users">
    <thead><tr>
      <th>User</th><th class="num">Jobs</th><th class="num">Characters</th>
      <th class="num">Tokens</th><th class="num">Cost, $</th>
    </tr></thead>
    <tbody></tbody>
  </table>

  <h2>History</h2>
  <div class="chips" id="chips"></div>
  <table id="history">
    <thead id="history-head"></thead>
    <tbody></tbody>
  </table>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const AGENT_LABELS = { doc_translator: "📄 translate", pdf_tts: "🔊 audio", yt_dub: "🎬 dub" };
"use strict";
const DATA = JSON.parse(document.getElementById("data").textContent);
const state = { user: null, status: null, sort: { col: "id", dir: -1 } };

const fmtInt = (n) => n == null ? "—" : Number(n).toLocaleString("en-US");
const fmtCost = (n) => n == null ? "—" : "$" + Number(n).toFixed(4);
const fmtDur = (n) => n == null ? "—" : Number(n).toFixed(1) + "s";
const fmtKb = (n) => n == null ? "—" : (n / 1024).toFixed(0) + " KB";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function parseTs(ts) { return ts ? new Date(ts.replace(" ", "T") + "Z") : null; }
function relTime(ts) {
  const d = parseTs(ts);
  if (!d) return el("span", "dim", "—");
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  let text;
  if (s < 60) text = Math.round(s) + "s ago";
  else if (s < 3600) text = Math.round(s / 60) + "m ago";
  else if (s < 86400) text = Math.round(s / 3600) + "h ago";
  else text = Math.round(s / 86400) + "d ago";
  const t = el("time", null, text);
  t.dateTime = d.toISOString();
  t.title = d.toLocaleString();
  return t;
}

function badge(status) {
  const map = { ok: ["ok", "✓ ok"], error: ["err", "✕ error"], running: ["run", "⟳ running"] };
  const [cls, label] = map[status] || ["run", status];
  return el("span", "badge " + cls, label);
}

function userLabel(row) {
  return row.username ? "@" + row.username : "id " + row.telegram_id;
}

// --- KPI tiles -------------------------------------------------------------

function sparkline(days) {
  const W = 150, H = 34, max = Math.max(...days.map(d => d.v), 1e-9);
  const step = days.length > 1 ? W / (days.length - 1) : 0;
  const pts = days.map((d, i) => [i * step, H - 3 - (H - 8) * (d.v / max)]);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", W); svg.setAttribute("height", H);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "daily cost, last " + days.length + " days");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", pts.map(p => p.map(x => x.toFixed(1)).join(",")).join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "var(--accent)");
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-linejoin", "round");
  svg.appendChild(line);
  const last = pts[pts.length - 1];
  const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  dot.setAttribute("cx", last[0].toFixed(1)); dot.setAttribute("cy", last[1].toFixed(1));
  dot.setAttribute("r", "3"); dot.setAttribute("fill", "var(--accent)");
  svg.appendChild(dot);
  svg.append(Object.assign(document.createElementNS("http://www.w3.org/2000/svg", "title"),
    { textContent: days.map(d => d.label + ": $" + d.v.toFixed(4)).join("\\n") }));
  return svg;
}

function dailyCost(jobs, nDays) {
  const days = [];
  const today = new Date(); today.setHours(0, 0, 0, 0);
  for (let i = nDays - 1; i >= 0; i--) {
    const d = new Date(today); d.setDate(d.getDate() - i);
    days.push({ key: d.toISOString().slice(0, 10), label: d.toISOString().slice(5, 10), v: 0 });
  }
  const index = Object.fromEntries(days.map(d => [d.key, d]));
  for (const j of jobs) {
    const ts = parseTs(j.created_at);
    if (!ts) continue;
    const key = ts.toISOString().slice(0, 10);
    if (index[key]) index[key].v += j.cost_usd || 0;
  }
  return days;
}

function renderKpis() {
  const box = document.getElementById("kpis");
  box.replaceChildren();
  const t = DATA.totals;
  const totalTokens = DATA.by_user.reduce((a, u) => a + (u.tokens || 0), 0);

  const cost = el("div", "tile");
  cost.append(el("div", "label", "Total cost"));
  cost.append(el("div", "value", "$" + (t.cost_usd || 0)));
  cost.append(sparkline(dailyCost(DATA.jobs, 14)));
  cost.append(el("div", "sub", "daily, last 14 days"));

  const jobs = el("div", "tile");
  jobs.append(el("div", "label", "Jobs"));
  jobs.append(el("div", "value", fmtInt(t.jobs || 0)));
  jobs.append(el("div", "sub", (t.ok_jobs || 0) + " ok · " + (t.error_jobs || 0) + " failed"));

  const tok = el("div", "tile");
  tok.append(el("div", "label", "Tokens"));
  tok.append(el("div", "value", fmtInt(totalTokens)));
  tok.append(el("div", "sub", "translation in + out"));

  const errRate = t.jobs ? (100 * (t.error_jobs || 0) / t.jobs) : 0;
  const err = el("div", "tile clickable" + (state.status === "error" ? " active" : ""));
  err.append(el("div", "label", "Error rate"));
  err.append(el("div", "value", errRate.toFixed(1) + "%"));
  err.append(el("div", "sub", state.status === "error" ? "filtering errors — click to clear" : "click to see failed jobs"));
  err.onclick = () => { state.status = state.status === "error" ? null : "error"; render(); };

  box.append(cost, jobs, tok, err);
}

// --- by-user table ---------------------------------------------------------

function renderUsers() {
  const body = document.querySelector("#users tbody");
  body.replaceChildren();
  if (!DATA.by_user.length) {
    const tr = el("tr"); const td = el("td", "empty", "No jobs yet.");
    td.colSpan = 5; tr.append(td); body.append(tr);
    return;
  }
  for (const u of DATA.by_user) {
    const tr = el("tr");
    if (state.user === u.telegram_id) tr.style.outline = "2px solid var(--accent)";
    tr.append(el("td", null, userLabel(u)));
    tr.append(el("td", "num", fmtInt(u.jobs)));
    tr.append(el("td", "num", fmtInt(u.chars)));
    tr.append(el("td", "num", fmtInt(u.tokens)));
    tr.append(el("td", "num", (u.cost_usd || 0).toFixed(4)));
    tr.title = "Filter history to this user";
    tr.onclick = () => { state.user = state.user === u.telegram_id ? null : u.telegram_id; render(); };
    body.append(tr);
  }
}

// --- history table ---------------------------------------------------------

const COLS = [
  { key: "created_at", label: "When" },
  { key: "username", label: "User" },
  { key: "agent", label: "Agent" },
  { key: "filename", label: "File" },
  { key: "tokens", label: "Tokens", num: true },
  { key: "cost_usd", label: "Cost, $", num: true },
  { key: "duration_s", label: "Time", num: true },
  { key: "status", label: "Status" },
];

function jobTokens(j) { return (j.input_tokens || 0) + (j.output_tokens || 0); }

function renderHistoryHead() {
  const head = document.getElementById("history-head");
  head.replaceChildren();
  const tr = el("tr");
  for (const c of COLS) {
    const th = el("th", c.num ? "num" : null);
    th.append(document.createTextNode(c.label + " "));
    if (state.sort.col === c.key) th.append(el("span", "sort-ind", state.sort.dir > 0 ? "▲" : "▼"));
    th.onclick = () => {
      state.sort = { col: c.key, dir: state.sort.col === c.key ? -state.sort.dir : 1 };
      render();
    };
    tr.append(th);
  }
  head.append(tr);
}

function sortValue(j, col) {
  if (col === "tokens") return jobTokens(j);
  if (col === "created_at") return j.created_at || "";
  const v = j[col];
  return v == null ? -Infinity : v;
}

function renderChips() {
  const box = document.getElementById("chips");
  box.replaceChildren();
  const mk = (label, clear) => {
    const chip = el("span", "chip", label + " ");
    const x = el("button", null, "×"); x.title = "Clear filter"; x.onclick = clear;
    chip.append(x); box.append(chip);
  };
  if (state.user != null) {
    const u = DATA.by_user.find(u => u.telegram_id === state.user);
    mk("user: " + (u ? userLabel(u) : state.user), () => { state.user = null; render(); });
  }
  if (state.status != null) mk("status: " + state.status, () => { state.status = null; render(); });
  if (state.user == null && state.status == null) {
    box.append(el("span", "hint", "Click a user row, the error tile, or column headers. Click a job for details."));
  }
}

function detailRow(j, colspan) {
  const tr = el("tr", "detail");
  const td = el("td"); td.colSpan = colspan;
  const facts = el("div", "dim",
    "file " + fmtKb(j.file_size_bytes) + " → output " + fmtKb(j.output_size_bytes) +
    " · chars " + fmtInt(j.char_count) +
    (j.tts_chars_billed ? " · tts chars " + fmtInt(j.tts_chars_billed) : "") +
    " · finished " + (j.finished_at || "—"));
  td.append(facts);
  if (j.error) {
    const err = el("div", null, "Error: " + j.error);
    err.style.color = "var(--bad)"; err.style.marginTop = "6px";
    td.append(err);
  }
  if (j.config_json) {
    const pre = el("pre", null, "config  " + JSON.stringify(j.config_json, null, 1));
    td.append(pre);
  }
  if (j.stats_json) {
    const pre = el("pre", null, "stats   " + JSON.stringify(j.stats_json, null, 1));
    td.append(pre);
  }
  tr.append(td);
  return tr;
}

function renderHistory() {
  renderHistoryHead();
  const body = document.querySelector("#history tbody");
  body.replaceChildren();
  let rows = DATA.jobs.slice();
  if (state.user != null) rows = rows.filter(j => j.telegram_id === state.user);
  if (state.status != null) rows = rows.filter(j => j.status === state.status);
  rows.sort((a, b) => {
    const va = sortValue(a, state.sort.col), vb = sortValue(b, state.sort.col);
    return (va < vb ? -1 : va > vb ? 1 : 0) * state.sort.dir;
  });
  if (!rows.length) {
    const tr = el("tr"); const td = el("td", "empty", "No jobs match the current filters.");
    td.colSpan = COLS.length; tr.append(td); body.append(tr);
    return;
  }
  for (const j of rows) {
    const tr = el("tr", "row");
    const tdWhen = el("td"); tdWhen.append(relTime(j.created_at)); tr.append(tdWhen);
    tr.append(el("td", null, userLabel(j)));
    tr.append(el("td", null, AGENT_LABELS[j.agent] || j.agent));
    const tdFile = el("td", "filename", j.filename || "—"); tdFile.title = j.filename || "";
    tr.append(tdFile);
    tr.append(el("td", "num", fmtInt(jobTokens(j) || null)));
    tr.append(el("td", "num", j.cost_usd == null ? "—" : j.cost_usd.toFixed(4)));
    tr.append(el("td", "num", fmtDur(j.duration_s)));
    const tdStatus = el("td"); tdStatus.append(badge(j.status)); tr.append(tdStatus);
    const detail = detailRow(j, COLS.length);
    tr.onclick = () => detail.classList.toggle("open");
    body.append(tr, detail);
  }
}

function render() { renderKpis(); renderUsers(); renderChips(); renderHistory(); }
render();

const loadedAt = Date.now();
setInterval(() => {
  const s = Math.round((Date.now() - loadedAt) / 1000);
  document.getElementById("updated").textContent =
    s < 5 ? "just now" : s < 60 ? s + "s ago" : Math.round(s / 60) + "m ago";
}, 5000);
</script>
</body>
</html>"""


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(title="ai_agents usage dashboard", version="0.2.0")
    # Loopback-only by deploy, but with no Host check a DNS-rebinding page could still
    # read /api/usage through the operator's browser while the SSH tunnel is open
    # (see the security review, L5).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/usage")
    def api_usage(limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
        return {
            "totals": db.query_totals(),
            "by_user": db.query_by_user(),
            "by_user_agent": db.query_by_user_agent(),
            "jobs": db.query_history(limit),
        }

    @app.get("/", response_class=HTMLResponse)
    def index(limit: int = Query(200, ge=1, le=1000)) -> str:
        payload = {
            "totals": db.query_totals(),
            "by_user": db.query_by_user(),
            "jobs": db.query_history(limit),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        # <-escape keeps user-controlled strings from closing the script tag.
        blob = json.dumps(payload, ensure_ascii=False, default=str).replace("<", "\\u003c")
        return _PAGE.replace("__DATA__", blob)

    return app
