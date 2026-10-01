# 14 — "Показать в чате" from the Mini App

**What to build:** ADR-0008. Every Item saved from now on remembers its original message. The item view in the Mini App has "💬 Показать в чате": the app closes and the bot replies to the original message, so tapping the quote jumps to it. If the original is gone, a Voice or File is sent again by `file_id`, and a Link or Note gets "Оригинал удалён".

**Blocked by:** 13 — Voice Items

**Status:** deployed 2026-10-01; live test green

**Checks** (no automated tests, ADR-001):
- [x] `POST /api/notes/items/{id}/show` sets the request; 409 for an Item with no original message, 404 for a missing one
- [x] `claim_show_requests` returns each request once and clears it
- [x] Deployed: the button on a new Item replies to its original in the chat; after deleting a test original, the voice comes back by `file_id`
- [x] Items saved before the deploy show no button
