---
skill: styles
---

<!-- fix -->
**Compare then fix:** Contrast **`<stem>.md`** emphasis with excerpt **`spans`** (bold/italic flags, font) or HTML **`<strong>`** / **`<em>`**. Where GFM `**` / `*` disagrees with the excerpt, fix the Markdown.

**Incremental:** Per **shared**, align emphasis **section by section**, then scan the **whole** file for missed or mismatched `**` / `*`.

**Phase: styles** — Fix **inline emphasis** (bold / italic) in **`<stem>.md`**.

**Output shape:** Even when no emphasis fixes are needed, your **final message must still be the complete** `<stem>.md` **file** (same as every improve phase). Do **not** answer with only an analysis, grep summary, or “no changes needed” report — that will replace the paper with a short fragment in the pipeline.

**PDF:** Each **line** in `<stem>.layout.json` may include **`spans`** with **`font`**, **`size`**, **`bold`**, **`italic`**, **`monospace`**, etc. (from PyMuPDF). Some PDFs omit flags or fake bold via font names — cross-check **`source.pdf`** when ambiguous.

- **PDF:** Use **`spans`** when present to align GFM `**` / `*` with the source; infer conservatively when flags are missing. Prefer **fixing malformed GFM** (`**` / `*` mismatches) over inventing new emphasis.
- **HTML:** Use `source.html` — `<strong>`, `<b>`, `<em>`, `<i>` map to `**…**`, `*…*`, or `***…***` as appropriate.
- **No excerpt:** Repair unmatched `*` / `**`, stray asterisks, and inconsistent emphasis; do not add new bold/italic unless clearly fixing a conversion error.

**GFM rules for this project:**
- Bold: `**text**`, italic: `*text*` (avoid `__` / `_` forms in new edits).
- Do not alter emphasis inside fenced code blocks or inline backticks.
- Do not alter table separator rows (`| --- |`).
- Do not change link targets, heading lines, or list markers.
- Do not rephrase wording — only fix emphasis markers.

Preserve all other content exactly as-is.


<!-- validate -->
Validate emphasis in the **Agent Output to Review**.

**HTML `source.html`:** When present, fail if strong/emphasis tags are not reflected in the Markdown with the expected `*` / `**` markers (allow equivalent GFM).

**PDF (layout JSON without span styles):** Pass if emphasis markers are **well-formed** and there is no obvious spurious `**` / `*` in prose. Fail on clearly broken or unmatched markers.

If all applicable checks pass, return {"pass": true, "reason": "ok"}.
