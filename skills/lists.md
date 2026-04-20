---
skill: lists
---

<!-- fix -->
**Compare then fix:** Contrast **list blocks** in **`<stem>.md`** with the excerpt (layout / HTML). Where **order, nesting, markers, or numbering** disagree, fix the Markdown.

**Incremental:** Per **shared**, fix **each list block** in reading order, then scan the full file for any remaining list issues.

**Phase: lists** — Fix list formatting in **`<stem>.md`**.

- **PDF / HTML excerpt:** Match list **structure** (nesting, item order, numbering style) to the source. Do not “fix” non-sequential numbering if the source is non-sequential.
- **Unordered lists:** use `-` for every item (not `*` or `+`).
- **Ordered lists:** use `1.`, `2.`, … when normalizing without an excerpt; preserve source numbering when the excerpt requires it.
- Indent nested levels with **2 spaces** per level.
- Blank lines: use a blank line between items only when an item has multiple paragraphs.
- Preserve all non-list text exactly as-is.


<!-- validate -->
Validate lists in the **Agent Output to Review**.

**Excerpt present:** Pass when list structure matches the source. Fail if items were merged, split, or renumbered away from the excerpt.

**No excerpt:** Pass only if unordered items use `-`, ordered lists are consistent with the fix rules, and nesting uses 2 spaces per level.

If all applicable checks pass, return {"pass": true, "reason": "ok"}.
