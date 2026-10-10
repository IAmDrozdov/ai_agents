# ADR-021: The Mini App navigates by Place and Mode, and an Item is closed from the list

Status: Proposed (2026-10-10). Supersedes ADR-020 decision 4 (tabs, the toggle, opening on the Dashboard); amends ADR-016 (decision 5: what a launch opens) and ADR-019 (decision 3: the phone also keeps the navigation memory).

## Context

Measured on 2026-10-10 in the owner's main client, Telegram for macOS (a 400 × 644 px page): the tab row and
the `[Дашборд | …]` toggle of ADR-020 took 106 px of every screen; the first Item of «Работа» sat 608 px
down the list (195 px when coming from the Dashboard), so none of its seven Items was fully visible; closing it
took three taps and a scroll; and the Item view began 156 px down. Every launch opened the notes Dashboard,
while the owner comes to pick a task in one Section and close it, or to write today's diary Entries. The app
remembered nothing between launches. The owner chose the design below from three navigation models, then
from four refinements of the third.

## Decision

1. **Two Places, each with two Modes, behind one title row.** The Places are «Заметки» and «Дневник»; a Mode
   is «записи» (the working view) or «дашборд». The only permanent navigation is a 48 px row: a button that
   names both («Заметки · записи ▾») and, to its right, the working view's own actions. The button opens a
   menu: one row per Place with a `[Записи | Дашборд]` segment, then «⚙️ Расходы». A tap on a Place's name
   opens it in the Mode it was left in, which the segment shows; a tap on a segment opens that Mode.
2. **A nested screen has no title row.** «Расходы», the Item view, the Section form and the diary's Week, Day,
   Month and Year are left with Telegram's back button. A client without one (Bot API below 6.1) gets a
   single «← Назад» button from the shell.
3. **The app remembers where the Owner was.** The last Place, each Place's Mode, the selected Section and
   whether the rail is shown are kept on the phone next to the snapshots (key `nav_v1`), and a 401 or 403
   wipes them too. A first launch opens «Заметки · записи». The «Готово» list, Search, an open Item, the
   diary's Week and the scroll position are not remembered. `/?item=<id>` opens that Item over the notes list
   whatever is remembered and leaves the memory alone. The Owner's Zone is reported on every launch, since
   the notes Dashboard is no longer the first screen.
4. **The notes list is a Section rail and one Section.** The rail has a button per Section (its emoji, or the
   first two letters of its name), «⏰» above them while anything is Overdue, and below them «✓» (the
   «Готово» list: one Status for the whole list, «Сделать» again at the next launch) and «✏️» (Section edit
   mode, as before). «◧» in the title row hides the rail; the Section's header then opens the list of
   Sections. «🔍» puts the Search field in place of the title row.
5. **An Item is a row, not a card.** The title (underlined when it is a link, which a tap opens), up to two
   lines of where it came from and its gist, then its Due or the state of its Enrichment, and a 36 px
   Thumbnail. The Section chips and the Owner's annotation show only in the Item view.
6. **One set of actions on an Item, reached four ways.** «⋮» in the row, a right click and a long press open
   the same menu: «✓ Готово» (or «↩ Вернуть в «Сделать»»), «⏰ Напомнить», «🗂 Секции…», «💬 Открыть в чате»,
   «↻ Разобрать заново» after a failed Enrichment, «🗑 Удалить». Swipes are shortcuts to it: left shows «Ещё»
   and «Готово», further left closes the Item, right opens its Due. Nothing is reachable by a gesture or by
   hovering alone. Closing shows at once and offers «↩ Вернуть» for four seconds; both are real Status
   changes, never a delayed one, and deleting keeps its confirm (notes ADR-0010).
7. **The Item view** has a row «Задача» with «⋮» (show in the chat, enrich again, delete). «✓ Готово» is
   Telegram's main button; pressing it saves an unsaved annotation, returns to the list and offers the same
   «↩ Вернуть». The Sections collapse to the Item's own and «Изменить…».
8. **The diary's working view is today's Day editor.** The Week is a nested screen, opened by «Неделя ›» or
   by the line under the editor, so «+ Добавить запись» is gone. A Day on the diary Dashboard opens its Week
   in «записи». In the editor an Entry has «+» (raise) and «✏️»; deleting it is inside the edit.

## Considered and rejected

- **One row with a «Заметки | Дневник» switch and Section chips above a single list.** The chips grow with
  the Sections: twelve take two or three lines, twenty would take four.
- **A bar pinned to the bottom of the window.** It costs 56 px of a 644 px window on every screen, and
  pinning was that design's own main risk: a sticky row has already slid under Telegram's header on iOS.
- **A title menu listing all five destinations.** Two Places with a Mode segment say the same in two rows
  and show which Mode a Place will open in.
- **A Mode switch inside the title button.** One tap less to change Mode, but it takes the room the working
  view's own actions need.
- **Swipes as the only way to close an Item.** A gesture nobody can see; «⋮» stays and the swipe speeds it up.
- **Staying on the Item view after «✓ Готово».** The Owner closes a task and goes on to the next one.
- **Pinning the rail.** Left to scroll with a long Section until it is checked on an iPhone, where a sticky
  row once slid under Telegram's header.

## Consequences

- Any place is two taps away instead of one or two; in return every screen gains 58 px, six of seven «Работа»
  Items fit the window, and closing the first one is two taps or one swipe.
- Telegram's main button is used for the first time: it must be hidden on every way out of the Item view.
- The phone holds a few more bytes of the Owner's state (`nav_v1`); nothing new is stored on the server.
- Text in a row cannot be selected, and a long title is cut at about three lines instead of being clamped.
- Still to be checked on the owner's devices: a right swipe at the left edge on iOS, a two-finger trackpad
  swipe in Telegram for macOS, and a menu near the bottom edge on iOS.
