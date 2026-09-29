# 08 — Sorting pass on the web

**What to build:** The web list becomes the sorting surface: filters by Sections (several at once), Status, Placement and unreviewed; pagination; inline actions on each row that re-render only that row — set Sections, Status, Placement, Reviewed, edit the Annotation, re-enrich, and hard-delete a trashed Item; bulk actions to archive everything done, mark the current view reviewed, and empty the Trash. The UI is Russian and the host header is restricted to localhost.

**Blocked by:** 05 — Filing and Gist by the Classifier

**Status:** ready-for-agent

- [ ] The unreviewed filter lists only unreviewed Items and stops listing an Item after any inline action on it (seam 7)
- [ ] Filtering by two Sections lists Items in either; filtering by Placement trashed lists only trashed Items; the default view lists only active Items with done ones last (seam 7)
- [ ] Setting an Item's Sections with none ticked leaves it in Other (seams 7 and 1)
- [ ] Archive-all-done moves every done active Item to archived and touches nothing else; mark-reviewed marks exactly the Items in the current filter (seams 7 and 1)
- [ ] Hard delete answers 409 for a non-trashed Item and removes a trashed one; empty-trash removes every trashed Item (seams 7 and 1)
- [ ] Re-enrich flips a failed Item back to pending and clears its error (seams 7 and 1)
- [ ] Editing the Annotation persists and is shown on the next request; all Owner and remote strings are escaped in the rendered HTML (seam 7)
- [ ] A request with a foreign `Host` header is refused with 400 (seam 7)
- [ ] Pagination shows 50 rows per page with working next/previous links (seam 7)
