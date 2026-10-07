// Item cards and the small formatters the cards and the item view share.

import { api, apiImageUrl, attempt, el, openUrl, parseTs } from "./core.js";

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

function sectionChip(section) {
  const chip = el("span", "chip", sectionLabel(section));
  chip.style.setProperty("--chip", section.color);
  return chip;
}

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

// opts: open(item), changed(item) for an item the card re-enriched, under (slug whose chip is left out),
// markDone (Search shows both Statuses).
export function card(item, opts) {
  const node = el("article", "card clickable");
  node.onclick = () => opts.open(item);
  if (item.thumb) {
    // the etag in the URL lets the webview keep the picture across launches (notes ADR-0012)
    const img = el("img", "thumb");
    img.alt = "";
    node.append(img);
    apiImageUrl(`/notes/items/${item.id}/thumb?v=${item.thumb}`).then((url) => {
      if (url) img.src = url;
      else img.remove();
    });
  }

  const body = el("div", "card-body");
  const title = itemTitle(item);
  if (item.kind === "link" && isHttp(item.url)) body.append(externalLink(item, title));
  else body.append(el("div", "title", title));
  const origin = originOf(item);
  if (origin) body.append(el("div", "origin", origin));
  if (item.kind === "file" && item.file_name) body.append(el("div", "origin", "📎 " + item.file_name));
  if (item.kind === "voice") body.append(el("div", "origin", "🎤 " + fmtDuration(item.duration_s)));
  if (item.gist) body.append(el("div", "gist", item.gist));
  if (item.kind !== "note" && item.text) body.append(el("div", "annotation", "✍️ " + item.text));

  const meta = el("div", "meta");
  if (opts.markDone && item.status === "done") meta.append(el("span", "badge ok", "✓ готово"));
  if (item.due_at) {
    const late = item.overdue;
    meta.append(el("span", late ? "badge late" : "badge due", `⏰ ${late ? "просрочено · " : ""}${fmtDue(item.due_at)}`));
  }
  for (const section of item.sections) if (section.slug !== opts.under) meta.append(sectionChip(section));
  if (meta.childElementCount) body.append(meta);

  if (item.enrichment_status === "pending") {
    body.append(enrichmentBadge(item));
  } else if (item.enrichment_status === "failed") {
    body.append(enrichmentBadge(item));
    const retry = el("button", "btn small", "Разобрать заново");
    retry.onclick = async (event) => {
      event.stopPropagation();
      const updated = await attempt(() => api(`/notes/items/${item.id}/reenrich`, { method: "POST" }));
      if (updated) opts.changed(updated);
    };
    body.append(retry);
  }
  node.append(body);
  return node;
}
