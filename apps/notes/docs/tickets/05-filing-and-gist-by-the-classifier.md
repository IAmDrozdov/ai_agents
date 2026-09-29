# 05 — Filing and Gist by the Classifier

**What to build:** Every Item gets a Filing into Sections and a Russian Gist from the Classifier, which sits behind the existing port (`notes.classify.port`) so the provider is configuration. The first real implementation is an **OpenAI adapter** (`notes/classify/openai.py`, ADR-015: every paid call in this repo goes to OpenAI); the deterministic fake stays for offline runs. The Classifier sees the fetched fields, the Annotation and the current list of all Sections with their hints. A refusal or a configuration error files the Item to Other with the error recorded; rate limits and outages go to backoff. The Acknowledgement shows the Sections and the Gist.

**Blocked by:** 04 — Enrichment without an LLM

**Status:** ready-for-agent

**Shape:**
- `NOTES_CLASSIFIER_PROVIDER` (`shared.config.Settings`) gains `openai`; `make_classifier` returns the adapter for it. The model defaults from `shared.pricing` (`DEFAULT_TRANSLATE_MODEL`) unless `NOTES_CLASSIFIER_MODEL` is set; the key is the existing `OPENAI_API_KEY`.
- Structured output (`client.chat.completions.parse` or `responses.parse` with the `Filing` model). A stable system prompt; the volatile Section list and the Item travel in the user turn. Build the client the way `shared.translate` does.
- Error mapping: `openai.RateLimitError`, `APIConnectionError`, `APITimeoutError`, 5xx `APIStatusError` → `ClassifierUnavailable`; `AuthenticationError`, `PermissionDeniedError`, `BadRequestError`, `NotFoundError` → `ClassifierRejected`; a refusal in the parsed message → `ClassifierRefused`.
- Log the call's token cost per Item (prices from `shared.pricing.translate_prices`). No spend gate: the admin is exempt from the daily cap and the volume is one person's.

**Checks** (no automated tests, ADR-001 — `notes-smoke` and the bot are the reference):
- [ ] `uv run notes-smoke <url>` with `NOTES_CLASSIFIER_PROVIDER=openai` prints Sections drawn only from the current slugs and a Russian Gist of one or two sentences, no emoji
- [ ] A Rust-async talk lands in Посмотреть (and Пет-проекты), a ramen place in Поесть, a joke tweet in Остальное
- [ ] An unknown slug in the answer is dropped; an empty Section list becomes Other (already enforced by `items._replace_sections`)
- [ ] With a wrong `OPENAI_API_KEY` the Item is filed to Other with the error visible on the web and no retry; with the network cut, it goes to backoff and the sweeper finishes it later
- [ ] In the bot, the edited Acknowledgement shows the Section line, the bold title and the Gist
- [ ] `NOTES_CLASSIFIER_PROVIDER=fake` still runs everything offline; switching `NOTES_CLASSIFIER_MODEL` needs no code change
