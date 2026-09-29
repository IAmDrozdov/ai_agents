// Entry: checks the Telegram launch, then draws the tabs and mounts one view at a time.

import { el, handleError, isHalted, prepareShell, setBack, showMessage, tg } from "./core.js";
import { mountNotes } from "./notes.js";
import { mountSections } from "./sections.js";
import { mountUsage } from "./usage.js";

const TABS = [
  { id: "notes", label: "Заметки", mount: mountNotes },
  { id: "sections", label: "Секции", mount: mountSections },
  { id: "usage", label: "Расходы", mount: mountUsage },
];

function boot() {
  if (!tg?.initData) {
    showMessage("Открой приложение из Telegram: кнопка 📒 в чате с ботом.");
    return;
  }
  prepareShell();

  const tabs = document.getElementById("tabs");
  const view = document.getElementById("view");
  view.replaceChildren(el("p", "empty", "Загрузка…"));

  // The ✏️ Открыть button in the chat launches the app with ?item=<id>.
  const item = new URLSearchParams(location.search).get("item");
  let launch = { itemId: item && /^\d+$/.test(item) ? item : null };
  let ticket = 0;

  function select(id) {
    const mine = ++ticket;
    for (const button of tabs.children) button.classList.toggle("on", button.dataset.tab === id);
    setBack(null);
    // A view is built off-screen and swapped in once its data is here: the page never collapses to a blank.
    const pane = el("div", "pane");
    const mounted = TABS.find((tab) => tab.id === id).mount(pane, { ...launch, alive: () => mine === ticket });
    launch = {};
    mounted.catch(handleError).finally(() => {
      if (mine !== ticket || isHalted()) return;
      view.replaceChildren(pane);
      window.scrollTo(0, 0);
    });
  }

  for (const tab of TABS) {
    const button = el("button", "tab", tab.label);
    button.dataset.tab = tab.id;
    button.onclick = () => select(tab.id);
    tabs.append(button);
  }
  select(TABS[0].id);
}

boot();
