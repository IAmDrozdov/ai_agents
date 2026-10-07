# Filing is optimistic, with a Reviewed flag — there is no inbox

_Amended by ADR-0010 (2026-10-07): the Reviewed flag and the sorting pass are gone. Filing stays optimistic with no inbox; the Classifier files only an Item that is in Other alone._

The Classifier files every Item into Sections at Capture and the Item lands there immediately;
`reviewed` records whether the Owner has looked at that Filing since. We rejected an
inbox-until-confirmed model because an unreviewed inbox is exactly the unsorted pile the product
exists to remove: the first month the Owner skips the sorting pass, the inbox *is* Telegram
Saved Messages with extra steps.

## Considered Options

- Inbox with proposals, confirmed on the web or via bot buttons — rejected (recreates the pile).
- Optimistic filing with no flag — rejected (throws away the one bit that gives the sorting pass a list).

## Consequences

- The app must remain fully useful if the Owner never reviews anything. If a feature only works
  after review, the design has drifted back to an inbox.
- Reviewed flips on any Owner touch (web edit, explicit ✓, or a section change from the bot keyboard).
