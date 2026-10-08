// An app's tab: a `[Дашборд | …]` toggle over two views, each mounted once on first use and kept while the other shows.

import { el, handleError } from "./core.js";

// views: [{ id, label, mount(pane, ctx) }], the first opening first; each ctx has isCurrent() and open(viewId, arg).
// Returns the tab's { show({ view, ...arg }), shown(), hide() }; outer.isCurrent() is false while another tab shows.
export async function mountToggled(root, outer, views) {
  const toggle = el("div", "segmented app-toggle");
  const body = el("div");
  root.replaceChildren(toggle, body);

  const mounted = new Map(); // view id -> { pane, ready, ctl once mounted }
  let active = null; // the view on screen
  let ticket = 0;

  for (const view of views) {
    const button = el("button", "seg", view.label);
    button.dataset.view = view.id;
    button.onclick = () => select(view.id).then(() => mounted.get(view.id)?.ctl?.shown?.());
    toggle.append(button);
  }

  function entryOf(id) {
    let entry = mounted.get(id);
    if (!entry) {
      const pane = el("div");
      const view = views.find((v) => v.id === id);
      const ctx = { isCurrent: () => outer.isCurrent() && active === id, open: (to, arg) => open(to, arg) };
      entry = { pane, ready: view.mount(pane, ctx) };
      mounted.set(id, entry);
      entry.ready.catch(() => mounted.delete(id)); // a failed mount is tried again on the next tap
    }
    return entry;
  }

  // Fills the view while the previous one stays on screen, then swaps it in; true once it is showing.
  async function select(id, arg = {}) {
    const mine = ++ticket;
    const entry = entryOf(id);
    try {
      entry.ctl = await entry.ready;
      await entry.ctl.show(arg);
    } catch (error) {
      handleError(error);
      return false;
    }
    if (mine !== ticket) return false;
    if (active !== id) {
      if (active) mounted.get(active)?.ctl?.hide();
      active = id;
      for (const button of toggle.children) button.classList.toggle("on", button.dataset.view === id);
      body.replaceChildren(entry.pane);
      window.scrollTo(0, 0);
    }
    return true;
  }

  // A cross-link inside the tab, e.g. a Section bar on the Dashboard opening the Items view.
  async function open(id, arg) {
    if (await select(id, arg)) mounted.get(id)?.ctl?.shown?.();
  }

  return {
    // arg.view picks the view (default: the one the Owner left on); the rest goes to that view's show().
    show: ({ view, ...arg } = {}) => select(view ?? active ?? views[0].id, arg),
    shown: () => mounted.get(active)?.ctl?.shown?.(),
    hide: () => mounted.get(active)?.ctl?.hide(),
  };
}
