---
skill: line_breaks
---

<!-- fix -->
**Compare then fix:** Contrast **`<stem>.md`** with the excerpt **lines** / **bbox** (PDF) or HTML flow. Where **paragraph or line boundaries** disagree, fix the Markdown.

**Incremental:** Per **shared**, adjust breaks **section by section**, then a **full-file pass** for stray hard breaks or merged lines.

**Phase: line_breaks** — Fix paragraph and intentional line breaks in **`<stem>.md`**.

**Ground rule — match the excerpt line count:** If a stretch of body text appears as **one line** in the excerpt (one **line** object in `<stem>.layout.json` for PDF, or one continuous run in `source.html` for HTML), the Markdown for that text must **read as one inline paragraph**: do **not** split it across multiple source lines with hard breaks (two trailing spaces + newline) or extra blank lines that turn it into stacked “pseudo-lines.” Soft-wrap in the file is fine; what matters is **no spurious line breaks** inside that single excerpt line. **Check every such case** against the excerpt, not only obvious paragraphs.

In GFM, a **single** newline inside a paragraph is a soft break (renders as a space). **Hard** line breaks need **two trailing spaces** before `\n`, or a **blank line** for a new paragraph.

- **Multiple excerpt lines** for the same thought (stacked lines, label + value, verse, code-adjacent short lines): keep separation using trailing spaces + newline or a new paragraph where the excerpt shows separate lines / bbox bands.
- **One excerpt line** → **inline** in Markdown (one paragraph line or soft-wrapped continuation; no mistaken hard breaks).
- **Same vertical row (bbox):** If two or more **lines** or **spans** sit on the **same height** — their **`bbox`** **y** values overlap or match within normal tolerance (same `[y0, y1]` band, i.e. one typeset row) — treat them as **one inline run** in Markdown: join with spaces as needed, **no** hard line breaks between them. Only when **`bbox`** moves to a **new** vertical band (next line down) is a paragraph break or hard break appropriate.
- Do not add hard breaks inside normal flowing prose that the excerpt shows as a **single** line or **single row** by bbox.
- Do not change headings, fences, table rows, or list markers in this phase except where a line-break fix touches the same line (prefer minimal edits).

**`<stem>.layout.json`:** Each **line** under a block is a separate excerpt line unless merged by the producer; compare **`bbox`** (especially shared **y0**/**y1** / row alignment) when deciding if two layout lines are one wrapped row vs two intentional lines.

Preserve all wording; only adjust newlines/spaces per the rules.


<!-- validate -->
Validate the **Agent Output to Review** for line-break issues against the excerpt.

**Classes of failure:**
1. **Single excerpt line** but Markdown uses hard line breaks or blank lines so the text no longer “flows” as one paragraph (must be inline / one paragraph).
2. **Multiple excerpt lines** that should render separately but are joined with only a soft newline (and should not be one paragraph).
3. Spurious two trailing spaces in the middle of text that the excerpt shows as one line.

**PDF:** Use **`pages[].blocks[].lines`** (and **`spans`** **`bbox`** when present) — if there is **one** `line` for a sentence or clause block, the output must not split it with hard breaks. If there are **several** `lines`, compare **`bbox`**: overlapping or identical vertical extent → **inline**; clearly different **y** bands → separate lines. Fail if same-row bbox text is hard-broken in Markdown.

**HTML:** Compare DOM / text nodes to the excerpt; one logical line in the source should not become multiple broken lines in Markdown without justification.

If all applicable checks pass, return {"pass": true, "reason": "ok"}.
