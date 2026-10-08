// Entry: checks the Telegram launch, then draws the app tabs and ⚙️ (ADR-020). A tab is mounted once per launch and
// keeps its state while another is shown; «Расходы» opens over the tabs and Telegram's back button returns.

import { OVERDUE } from "./cards.js";
import { el, handleError, isHalted, loadSnapshots, prepareShell, setBack, showMessage, tg } from "./core.js";
import { mountDashboard, reportZone } from "./dashboard.js";
import { mountDiaryBoard } from "./diaryboard.js";
import { mountWeek } from "./diary.js";
import { mountNotes } from "./notes.js";
import { mountToggled } from "./toggled.js";
import { mountUsage } from "./usage.js";

// One tab per app, each opening on its Dashboard; `views` are the two sides of its toggle.
const TABS = [
  {
    id: "notes",
    label: "Заметки",
    views: [
      {
        id: "dashboard",
        label: "Дашборд",
        mount: (pane, ctx) =>
          mountDashboard(pane, {
            ...ctx,
            openSection: (slug) => ctx.open("items", { expand: slug }),
            openOverdue: () => ctx.open("items", { expand: OVERDUE }),
          }),
      },
      { id: "items", label: "Заметки", mount: mountNotes },
    ],
  },
  {
    id: "diary",
    label: "Дневник",
    views: [
      { id: "dashboard", label: "Дашборд", mount: mountDiaryBoard },
      { id: "week", label: "Записи", mount: mountWeek },
    ],
  },
];

async function boot() {
  if (!tg?.initData) {
    showMessage("Открой приложение из Telegram: кнопка 📒 в чате с ботом.");
    return;
  }
  prepareShell();

  const tabs = document.getElementById("tabs");
  const view = document.getElementById("view");
  view.replaceChildren(el("p", "empty", "Загрузка…"));

  const views = new Map(); // tab id -> { pane, ready: Promise<{ show, shown?, hide }>, ctl once mounted }
  let current = null; // the tab or "usage" the Owner asked for last
  let onScreen = null; // the tab whose pane is showing
  let lastTab = TABS[0].id;
  let ticket = 0;


  // Runs before the next view is swapped in: hide() may close an overlay, which resets the back button and scroll.
  function leave() {
    const shownBefore = onScreen && views.get(onScreen);
    onScreen = null;
    shownBefore?.ctl?.hide();
  }

  // A view is filled while the previous one stays on screen, then swapped in once: the page never goes blank.
  async function select(id, arg) {
    const mine = ++ticket;
    current = id;
    lastTab = id;
    let entry = views.get(id);
    if (!entry) {
      const pane = el("div", "pane");
      const tab = TABS.find((t) => t.id === id);
      entry = { pane, ready: mountToggled(pane, { isCurrent: () => current === id }, tab.views) };
      views.set(id, entry);
      entry.ready.catch(() => views.delete(id)); // a failed mount is tried again on the next tap
    }
    try {
      const ctl = await entry.ready;
      entry.ctl = ctl;
      await ctl.show(arg);
      if (mine !== ticket || isHalted()) return;
      if (onScreen === id) return; // the tab already showing just reloaded; an open item view stays
      leave();
      for (const button of tabs.querySelectorAll(".tab")) button.classList.toggle("on", button.dataset.tab === id);
      tabs.hidden = false;
      setBack(null);
      view.replaceChildren(entry.pane);
      onScreen = id;
      window.scrollTo(0, 0);
      ctl.shown?.();
    } catch (error) {
      handleError(error);
    }
  }

  function openUsage() {
    const mine = ++ticket;
    current = "usage";
    const back = () => select(lastTab);
    const closeButton = el("button", "btn small ghost", "← Назад");
    closeButton.onclick = back;
    const body = el("div");
    const pane = el("div", "pane");
    pane.append(closeButton, body);
    mountUsage(body)
      .catch(handleError)
      .finally(() => {
        if (mine !== ticket || isHalted()) return;
        leave();
        tabs.hidden = true;
        view.replaceChildren(pane);
        window.scrollTo(0, 0);
        setBack(back);
      });
  }

  for (const tab of TABS) {
    const button = el("button", "tab", tab.label);
    button.dataset.tab = tab.id;
    button.onclick = () => select(tab.id);
    tabs.append(button);
  }
  const gear = el("button", "tab gear", "⚙️");
  gear.setAttribute("aria-label", "Расходы");
  gear.onclick = openUsage;
  tabs.append(gear);

  await loadSnapshots(); // the last launch's answers: the first tab paints from them, then revalidates

  // The ✏️ Открыть button in the chat launches the app with ?item=<id>.
  const item = new URLSearchParams(location.search).get("item");
  if (item && /^\d+$/.test(item)) {
    reportZone();
    select("notes", { view: "items", itemId: item });
  }
  else select(TABS[0].id);
}

boot();
