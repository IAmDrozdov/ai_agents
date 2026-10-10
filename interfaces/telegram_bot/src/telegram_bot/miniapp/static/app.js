// Entry: checks the Telegram launch, then draws the top bar and the place the Owner left on (ADR-021). A view is
// mounted once per launch and keeps its state while another shows; «Расходы» and every nested screen open without
// the bar, and Telegram's back button returns.

import { OVERDUE } from "./cards.js";
import {
  el,
  handleError,
  hideMainButton,
  isHalted,
  loadStored,
  prefs,
  prepareShell,
  savePrefs,
  setBack,
  showMessage,
  tg,
} from "./core.js";
import { mountDashboard, reportZone } from "./dashboard.js";
import { mountDiaryBoard } from "./diaryboard.js";
import { mountToday } from "./diary.js";
import { closeMenu, mountTopbar } from "./nav.js";
import { mountNotes } from "./notes.js";
import { mountUsage } from "./usage.js";

// Every place has the same two modes: its working view and its Dashboard.
const MODES = [
  { id: "list", label: "Записи", word: "записи" },
  { id: "board", label: "Дашборд", word: "дашборд" },
];
const PLACES = [
  {
    id: "notes",
    label: "Заметки",
    mount: {
      list: mountNotes,
      board: (pane, ctx) =>
        mountDashboard(pane, {
          ...ctx,
          openSection: (slug) => ctx.open("list", { section: slug }),
          openOverdue: () => ctx.open("list", { section: OVERDUE }),
        }),
    },
  },
  { id: "diary", label: "Дневник", mount: { list: mountToday, board: mountDiaryBoard } },
];

// The mode a place opens in: the one the Owner left it in, the working view on a first launch.
const modeOf = (place) => {
  const kept = prefs().mode?.[place];
  return MODES.some((mode) => mode.id === kept) ? kept : MODES[0].id;
};

async function boot() {
  if (!tg?.initData) {
    showMessage("Открой приложение из Telegram: кнопка 📒 в чате с ботом.");
    return;
  }
  prepareShell();

  const bar = document.getElementById("topbar");
  const view = document.getElementById("view");
  view.replaceChildren(el("p", "empty", "Загрузка…"));

  const views = new Map(); // "place:mode" -> { place, mode, pane, ready, ctl once mounted, bar: the view's own actions }
  let current = null; // the view or "usage" the Owner asked for last
  let onScreen = null; // the view whose pane is showing
  let barKey = null; // the view whose title row is drawn
  let last = null; // { place, mode } asked for last: «Расходы» returns to it
  let ticket = 0;

  const topbar = mountTopbar(bar, {
    places: PLACES,
    modes: MODES,
    remembered: modeOf,
    go: (place, mode) => select(place, mode, undefined, true),
    usage: openUsage,
  });
  function paintBar(entry) {
    barKey = `${entry.place}:${entry.mode}`;
    topbar.set({ place: entry.place, mode: entry.mode, ...entry.bar });
  }

  // Runs before the next view is swapped in: hide() may close a nested screen, which resets the back button and scroll.
  function leave() {
    const shownBefore = onScreen && views.get(onScreen);
    onScreen = null;
    closeMenu(); // one opened while the next view was loading belongs to the view that goes
    shownBefore?.ctl?.hide();
  }

  function entryOf(place, mode) {
    const key = `${place}:${mode}`;
    let entry = views.get(key);
    if (!entry) {
      entry = { place, mode, pane: el("div", "pane"), bar: {} };
      const ctx = {
        isCurrent: () => current === key,
        // A cross-link inside the place, e.g. a Section bar on the Dashboard opening the list.
        open: (to, arg) => select(place, to, arg, true),
        // The view's own part of the top bar: { left, right, replace } (nav.js mountTopbar).
        setBar: (parts) => {
          entry.bar = parts;
          if (barKey === key) paintBar(entry);
        },
      };
      entry.ready = PLACES.find((p) => p.id === place).mount[mode](entry.pane, ctx);
      views.set(key, entry);
      entry.ready.catch(() => views.delete(key)); // a failed mount is tried again on the next tap
    }
    return entry;
  }

  // A view is filled while the previous one stays on screen, then swapped in once: the page never goes blank.
  // `remember` writes the navigation memory: the Owner's own moves do, a launch and the way back from «Расходы» do not.
  async function select(place, mode, arg, remember = false) {
    const mine = ++ticket;
    const key = `${place}:${mode}`;
    current = key;
    last = { place, mode };
    closeMenu();
    const entry = entryOf(place, mode);
    try {
      const ctl = await entry.ready;
      entry.ctl = ctl;
      await ctl.show(arg);
      if (mine !== ticket || isHalted()) return;
      if (remember) savePrefs({ place, mode: { [place]: mode } });
      if (onScreen !== key) {
        leave();
        setBack(null);
        hideMainButton();
        paintBar(entry);
        view.replaceChildren(entry.pane);
        onScreen = key;
        window.scrollTo(0, 0);
      }
      ctl.shown?.();
    } catch (error) {
      handleError(error);
    }
  }

  function openUsage() {
    const mine = ++ticket;
    current = "usage";
    const back = () => select(last.place, last.mode);
    closeMenu();
    const pane = el("div", "pane");
    mountUsage(pane)
      .catch(handleError)
      .finally(() => {
        if (mine !== ticket || isHalted()) return;
        leave();
        hideMainButton();
        view.replaceChildren(pane);
        window.scrollTo(0, 0);
        setBack(back);
      });
  }

  await loadStored(); // the last launch's answers and where the Owner was: the first view paints from them

  // The 📅 Перенести button in the chat launches the app with ?item=<id>: that Item over the list, whatever is remembered.
  const item = new URLSearchParams(location.search).get("item");
  const asked = item && /^\d+$/.test(item);
  const place = !asked && PLACES.some((p) => p.id === prefs().place) ? prefs().place : PLACES[0].id;
  const mode = asked ? MODES[0].id : modeOf(place);
  if (!(place === "notes" && mode === "board")) reportZone(); // the notes Dashboard tells the server the zone itself
  paintBar(entryOf(place, mode)); // the title row stands before the first answer: a slow link still shows where this is
  setBack(null);
  select(place, mode, asked ? { itemId: item } : undefined);
}

boot();
