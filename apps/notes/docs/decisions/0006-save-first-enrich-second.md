# Save first, enrich second

An Item is written to the database and Acknowledged before any network fetch or Classifier call;
Enrichment runs afterwards in the background, driven from the database (a sweeper in the bot
process is the retry queue) with backoff, and the Acknowledgement is edited in place when it
lands. A network, provider or LLM failure can therefore never lose a Capture — the product's
promise is that nothing thrown at the bot is lost.

## Considered Options

- Enrich synchronously and reply once with the full result — rejected: a slow or failing fetch delays or loses the one thing the Owner cares about, the confirmation that it is saved.

## Consequences

- Until Enrichment lands, the Item sits in *Other* with `enrichment_status = pending`; the invariant of ADR-0002 holds from the first millisecond.
- The database is the queue: a manual "re-enrich" from the web only flips the Item back to `pending`, and the bot's sweeper picks it up — no cross-process signalling.
- Restart recovery is a query, not a mechanism: `pending` Items with no scheduled retry that are older than a couple of minutes are simply due again.
