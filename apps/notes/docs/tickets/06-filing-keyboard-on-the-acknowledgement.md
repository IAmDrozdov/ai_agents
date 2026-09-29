# 06 — Filing keyboard on the Acknowledgement

**What to build:** Every Acknowledgement (and every dedupe reply) carries a keyboard: one toggle per Section, then Начато / Готово / В архив, and Вернуть when the Item is archived. One tap corrects a Filing or changes Status or Placement, and the message re-renders in place. Removing the last Section moves the Item to Other and says so. Any tap marks the Item Reviewed.

**Blocked by:** 05 — Filing and Gist by the Classifier

**Status:** replaced by the Mini App (ai_agents ADR-016). The item view sets Sections, Status and Placement, and the Acknowledgement carries one `✏️ Открыть` button that opens it, instead of a toggle keyboard. The criteria below are history.

- [ ] Tapping the Посмотреть toggle on an Item that is only in Other results in a Filing of exactly Посмотреть (Other removed), and the re-rendered keyboard shows ✅ on Посмотреть (seams 6 and 1)
- [ ] Tapping the only remaining Section off leaves the Item in Other and answers the callback with a toast mentioning Остальное (seams 6 and 1)
- [ ] Готово sets Status done; Начато sets started; В архив sets Placement archived and the keyboard gains Вернуть; Вернуть sets it back to active (seams 6 and 1)
- [ ] Reviewed is set after any tap (seam 1)
- [ ] Every callback data string generated for Item and Section ids up to 10⁹ is at most 64 bytes (seam 6)
- [ ] A tap on a keyboard belonging to an Item that no longer exists answers the callback with a clear message and does not crash the bot (seam 6)
- [ ] The dedupe reply for an existing Link carries the same keyboard and its taps work the same way (seam 6)
