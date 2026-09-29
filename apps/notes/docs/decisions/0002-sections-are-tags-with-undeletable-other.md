# Sections are tags, and Other is undeletable

An Item belongs to one or more Sections (tag semantics, not folders), so a cross-cutting Item — a
talk that is both *Посмотреть* and *Пет-проекты* — is not forced into one pile. The built-in
*Other* Section cannot be deleted and receives any Item that would otherwise have no Section, so
the invariant **every Item has at least one Section** holds everywhere and no view or query has a
null state to handle.

## Considered Options

- Exactly one Section per Item (folder semantics) — rejected by the Owner: cross-cutting Items are real.
- One primary Section plus free tags — rejected: two mechanisms for one idea; can be added later without breaking tags.
- Allowing an empty Section set with an "untagged" filter — rejected: the same pile as Other, but unnamed and special-cased.
- No catch-all, always pick a real Section — rejected: forces false confidence and quietly poisons real piles.

## Consequences

- Section views are filters; an Item appears in every Section it is in.
- Removing an Item's last Section (bot or web) moves it to Other rather than leaving it unfiled.
- Deleting a Section re-homes Items that had only that Section to Other in the same transaction.
