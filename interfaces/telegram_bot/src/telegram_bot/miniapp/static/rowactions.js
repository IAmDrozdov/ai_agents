// What a task row answers to (ADR-021): «⋮», a right click and a long press open one menu, and a swipe is its
// shortcut. Every listener sits on the node that holds the rows, never on a row.

import { openMenu } from "./nav.js";

const SLOP = 8; // px a pointer moves before the gesture has a direction
const LONG_PRESS_MS = 500;
const OPEN_AT = -50; // released left of this, the «Ещё» and «Готово» panel stays open
const DONE_AT = -170; // and left of this the task is closed at once
const REMIND_AT = 80;
const PANEL = -144; // the open panel: «Ещё» 68 px and «Готово» 76 px
const MIN = -260;
const MAX = 140;
const LEFT_EDGE = 24; // a touch this close to the left edge is iOS's own Back swipe
const WHEEL_IDLE_MS = 140; // a trackpad swipe ends when its scroll events stop
const CLICK_AFTER_MS = 80; // the click a browser sends after a gesture arrives within this

// root holds every `.row-wrap[data-id]` (cards.js row()). actions: itemOf(id), open(item), done(item), undone(item),
// remind(item), sections(item), show(item), reenrich(item), remove(item). Returns { close() }: every open row slides back.
export function attachRowActions(root, actions) {
  let gesture = null; // the pointer on a row: { row, x, y, dx, base, mode, pointerId, timer }
  let wheel = null; // the trackpad swipe in progress: { row, base, sum, live, timer }
  let swallowUntil = 0;

  const itemOf = (wrap) => actions.itemOf(Number(wrap.dataset.id));
  const offOf = (row) => Number(row.dataset.off || 0);

  function menuItems(item) {
    const items = [
      item.status === "todo"
        ? { icon: "✓", label: "Готово", tone: "good", run: () => actions.done(item) }
        : { icon: "↩", label: "Вернуть в «Сделать»", run: () => actions.undone(item) },
      { icon: "⏰", label: "Напомнить", run: () => actions.remind(item) },
      { icon: "🗂", label: "Секции…", run: () => actions.sections(item) },
    ];
    if (item.tg_message_id) items.push({ icon: "💬", label: "Открыть в чате", run: () => actions.show(item) });
    if (item.enrichment_status === "failed") {
      items.push({ icon: "↻", label: "Разобрать заново", run: () => actions.reenrich(item) });
    }
    items.push({ sep: true }, { icon: "🗑", label: "Удалить", tone: "danger", run: () => actions.remove(item) });
    return items;
  }

  function menuAt(wrap, at) {
    const item = itemOf(wrap);
    if (!item) return;
    const more = wrap.querySelector(".more");
    if (at) openMenu(more, menuItems(item), { at });
    else openMenu(more, menuItems(item), { align: "right" });
  }

  // The row's resting offset; back at 0 the panels hide once the row has slid home.
  function setOff(row, off) {
    row.dataset.off = String(off);
    row.style.transform = off ? `translateX(${off}px)` : "";
    if (off) {
      row.parentElement.dataset.dir = off < 0 ? "r" : "l"; // the timer of an earlier slide home may have hidden it
      return;
    }
    setTimeout(() => {
      if (!offOf(row)) delete row.parentElement?.dataset.dir;
    }, 200);
  }

  // Slides every open row but `except` back; true if there was one.
  function closeSwipes(except) {
    const open = [...root.querySelectorAll(".row[data-off]")].filter((row) => row !== except && offOf(row));
    for (const row of open) setOff(row, 0);
    return open.length > 0;
  }

  function drag(row, dx) {
    row.parentElement.dataset.dir = dx < 0 ? "r" : "l";
    row.style.transform = `translateX(${dx}px)`;
  }

  // Where the row was let go decides: close the task, leave the panel open, remind, or slide back.
  function settle(row, dx) {
    row.classList.remove("dragging");
    const item = itemOf(row.parentElement);
    if (!item || (dx >= OPEN_AT && dx <= REMIND_AT)) {
      setOff(row, 0);
    } else if (dx < DONE_AT) {
      row.style.transform = "translateX(-110%)";
      setTimeout(() => {
        (item.status === "todo" ? actions.done : actions.undone)(item);
        if (row.isConnected) setOff(row, 0); // a list that keeps the row (Search) shows it again
      }, 180);
    } else if (dx < OPEN_AT) {
      setOff(row, PANEL);
    } else {
      setOff(row, 0);
      actions.remind(item); // inside the gesture: a phone opens the date picker only for a call made there
    }
  }

  // Ends the gesture in progress without acting on it: a swiped row slides back.
  function abandon() {
    if (!gesture) return;
    const { row, mode, timer } = gesture;
    gesture = null;
    clearTimeout(timer);
    if (mode === "swipe") settle(row, 0);
  }

  root.addEventListener("pointerdown", (event) => {
    if (gesture?.mode === "swipe" && event.pointerId !== gesture.pointerId) return; // a second finger: the swipe goes on
    abandon();
    const row = event.target.closest(".row");
    if (!row || event.button !== 0 || event.target.closest(".more")) return;
    const touch = event.pointerType !== "mouse";
    if (touch && event.clientX < LEFT_EDGE) return;
    const at = { x: event.clientX, y: event.clientY };
    gesture = { row, ...at, dx: 0, base: offOf(row), mode: null, pointerId: event.pointerId, timer: 0 };
    if (!touch) return; // a held mouse button is a drag, never a long press
    const mine = gesture;
    gesture.timer = setTimeout(() => {
      if (gesture !== mine || mine.mode) return;
      mine.mode = "press";
      menuAt(row.parentElement, at);
    }, LONG_PRESS_MS);
  });

  root.addEventListener("pointermove", (event) => {
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    if (event.pointerType === "mouse" && !event.buttons) {
      abandon(); // the button went up outside the list, where no pointerup reaches it
      return;
    }
    const dx = event.clientX - gesture.x;
    const dy = event.clientY - gesture.y;
    if (!gesture.mode) {
      if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return;
      clearTimeout(gesture.timer);
      if (Math.abs(dx) <= Math.abs(dy)) {
        gesture = null; // vertical: the page scrolls
        return;
      }
      gesture.mode = "swipe";
      gesture.row.setPointerCapture(event.pointerId);
      gesture.row.classList.add("dragging");
      closeSwipes(gesture.row);
    }
    if (gesture.mode !== "swipe") return;
    gesture.dx = Math.max(MIN, Math.min(MAX, gesture.base + dx));
    drag(gesture.row, gesture.dx);
  });

  function endPointer(event, cancelled) {
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    const { row, mode, dx, timer } = gesture;
    gesture = null;
    clearTimeout(timer);
    if (!mode) return;
    swallowUntil = performance.now() + CLICK_AFTER_MS;
    if (mode === "swipe") settle(row, cancelled ? 0 : dx);
  }
  root.addEventListener("pointerup", (event) => endPointer(event, false));
  root.addEventListener("pointercancel", (event) => endPointer(event, true));
  // A swiped row redrawn under the finger loses the pointer (the event then comes from the document), and its
  // pointerup lands wherever the finger is. A touch moving its capture from the element first touched to the row
  // sends the same event from that element: not an end.
  document.addEventListener("lostpointercapture", (event) => {
    if (event.target === document || event.target === gesture?.row) endPointer(event, true);
  });

  // The click that follows a swipe or a long press belongs to the gesture: nothing else may act on it.
  document.addEventListener(
    "click",
    (event) => {
      if (performance.now() >= swallowUntil) return;
      swallowUntil = 0;
      event.preventDefault();
      event.stopPropagation();
    },
    true,
  );

  root.addEventListener("contextmenu", (event) => {
    const row = event.target.closest(".row");
    if (!row) return;
    event.preventDefault();
    if (gesture?.mode === "press") return; // Android sends this after its own long press: the menu is already up
    abandon();
    menuAt(row.parentElement, { x: event.clientX, y: event.clientY });
  });

  // A two-finger trackpad swipe arrives as horizontal scroll events; the row moves once they add up to a swipe.
  root.addEventListener(
    "wheel",
    (event) => {
      const row = event.target.closest(".row-wrap")?.querySelector(".row"); // the panels count: the row slides off them
      if (!row || Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
      event.preventDefault();
      if (wheel?.row !== row) wheel = { row, base: offOf(row), sum: 0, live: false, timer: 0 };
      const mine = wheel;
      mine.sum -= event.deltaX;
      if (!mine.live && Math.abs(mine.sum) >= SLOP) {
        mine.live = true;
        closeSwipes(row);
        row.classList.add("dragging");
      }
      const dx = Math.max(MIN, Math.min(MAX, mine.base + mine.sum));
      if (mine.live) drag(row, dx);
      clearTimeout(mine.timer);
      mine.timer = setTimeout(() => {
        if (wheel === mine) wheel = null;
        if (mine.live) settle(row, dx);
      }, WHEEL_IDLE_MS);
    },
    { passive: false },
  );

  root.addEventListener("click", (event) => {
    const wrap = event.target.closest(".row-wrap");
    if (!wrap) return;
    const item = itemOf(wrap);
    if (!item) return;
    const row = wrap.querySelector(".row");
    const act = event.target.closest("[data-act]")?.dataset.act;
    const closedAnother = closeSwipes(row);
    if (act === "more") {
      row.classList.add("dragging"); // no slide home: the menu hangs from where «⋮» comes to rest
      setOff(row, 0);
      menuAt(wrap, null);
      requestAnimationFrame(() => row.classList.remove("dragging"));
    } else if (act === "done") {
      (item.status === "todo" ? actions.done : actions.undone)(item);
    } else if (offOf(row)) {
      setOff(row, 0); // a tap on a row left open only closes it
    } else if (!closedAnother) {
      actions.open(item); // and so does a tap on any other row
    }
  });

  return { close: () => closeSwipes(null) };
}
