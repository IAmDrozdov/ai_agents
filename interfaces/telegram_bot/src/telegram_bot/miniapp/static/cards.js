// Item rows and the small formatters the rows and the item view share.

import { apiImageUrl, el, openUrl, parseTs } from "./core.js";

export const OTHER = "other";
export const OVERDUE = "__overdue"; // the slug of the «Просрочено» row, which is not a Section

export const isHttp = (url) => /^https?:\/\//i.test(url || "");
export const itemTitle = (item) =>
  item.title || item.url || item.file_name || item.text || (item.kind === "voice" ? "🎤 Голосовое" : "Без названия");
export const originOf = (item) =>
  [item.source, item.author, item.sender && "↪️ " + item.sender].filter(Boolean).join(" · ");

export function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function fmtDate(ts) {
  const date = parseTs(ts);
  return date ? date.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" }) : "—";
}

// A Due in the Owner's zone, as the chat prints it: «пт, 10 окт, 19:00».
export function fmtDue(ts) {
  const date = parseTs(ts);
  if (!date) return "—";
  const day = date.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" }).replace(".", "");
  return `${day}, ${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
}

const pad = (n) => String(n).padStart(2, "0");

// A moment as the value a datetime-local input takes, in the Owner's zone.
export function toLocalInput(when) {
  const d = typeof when === "string" ? parseTs(when) : when;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const sectionLabel = (section) => `${section.emoji} ${section.name}`.trim();

export function externalLink(item, title) {
  const link = el("a", "title", title);
  link.href = item.url;
  link.onclick = (event) => {
    event.preventDefault();
    event.stopPropagation();
    openUrl(item.url);
  };
  return link;
}

export function enrichmentBadge(item) {
  if (item.enrichment_status === "pending") return el("div", "badge run", "⏳ разбираю");
  const why = item.enrichment_error ? ": " + item.enrichment_error : "";
  return el("div", "badge err", "⚠️ не разобрано" + why);
}

const TITLE_CHARS = 120; // a row's title has no line clamp (the text flows round «⋮»), so a long one is cut
const FALLBACK_CHARS = 81; // a URL, a file name or a note's whole text standing in for a title

const clip = (text, n) => (text.length > n ? text.slice(0, n).trimEnd() + "…" : text);

// A row's second line: where the Item came from, then the bot's gist; a text note shows the Owner's own words.
function subOf(item, title) {
  const lead = [
    originOf(item),
    item.kind === "file" && item.file_name && item.file_name !== title && "📎 " + item.file_name,
    item.kind === "voice" && "🎤 " + fmtDuration(item.duration_s),
  ];
  const own = item.kind === "note" && item.text !== title && item.text;
  const body = own || item.gist;
  return [lead.filter(Boolean).join(" · "), body !== title && body].filter(Boolean).join(" — ");
}

// What the toast says after «Разобрать заново»: the Classifier files an Item again only from Other alone (ADR-0010).
export function reenrichToast(item) {
  const slugs = item.sections.map((section) => section.slug);
  const refiles = !slugs.length || (slugs.length === 1 && slugs[0] === OTHER);
  return refiles ? "Поставил в очередь" : "Поставил в очередь. Секции оставлю как есть";
}

// A part of a swipe panel: an icon over a word.
function panelPart(tag, icon, label, cls) {
  const node = el(tag, cls);
  node.append(el("span", null, icon), label);
  return node;
}

function panelButton(act, icon, label, cls) {
  const button = panelPart("button", icon, label, cls);
  button.dataset.act = act;
  return button;
}

// One Item in a list: `.row-wrap[data-id]` holding the two swipe panels and the row. rowactions.js gives it its
// taps, menu and swipes. opts.markDone: the list shows both Statuses (Search), so a done Item says so.
export function row(item, opts = {}) {
  const wrap = el("div", "row-wrap");
  wrap.dataset.id = String(item.id);
  const left = el("div", "acts acts-l");
  left.append(panelPart("div", "⏰", "Напомнить")); // a label: letting the row go over it opens the Due
  const right = el("div", "acts acts-r");
  const todo = item.status === "todo";
  right.append(panelButton("more", "⋯", "Ещё", "gray"), panelButton("done", todo ? "✓" : "↩", todo ? "Готово" : "Вернуть", "ok"));

  const node = el("article", "row");
  const more = el("button", "more", "⋮");
  more.dataset.act = "more";
  more.setAttribute("aria-label", "Действия");
  node.append(more);
  if (item.thumb) {
    // the etag in the URL lets the webview keep the picture across launches (notes ADR-0012)
    const img = el("img", "thumb");
    img.alt = "";
    img.draggable = false;
    node.append(img);
    apiImageUrl(`/notes/items/${item.id}/thumb?v=${item.thumb}`).then((url) => {
      if (url) img.src = url;
      else img.remove();
    });
  }

  const full = itemTitle(item);
  const title = clip(full, item.title ? TITLE_CHARS : FALLBACK_CHARS);
  if (item.kind === "link" && isHttp(item.url)) {
    const link = externalLink(item, title);
    link.draggable = false; // a mouse swipe that starts on the title must not drag the link away
    node.append(link);
  } else {
    node.append(el("div", "title", title));
  }
  const sub = subOf(item, full);
  if (sub) node.append(el("div", "sub", sub));

  const meta = el("div", "meta");
  const mark = (text, cls) => {
    if (meta.childNodes.length) meta.append(" · ");
    meta.append(el("span", cls, text));
  };
  if (opts.markDone && !todo) mark("✓ готово", "ok");
  if (item.due_at) mark(`⏰ ${item.overdue ? "просрочено · " : ""}${fmtDue(item.due_at)}`, item.overdue ? "late" : null);
  if (item.enrichment_status === "pending") mark("⏳ разбираю");
  else if (item.enrichment_status === "failed") mark("⚠️ не разобрано", "late");
  if (meta.childNodes.length) node.append(meta);

  wrap.append(left, right, node);
  return wrap;
}
