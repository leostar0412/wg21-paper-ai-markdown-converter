---
skill: code
---

<!-- fix -->
**Compare then fix:** Contrast each **fenced block** in **`<stem>.md`** with the excerpt (layout **lines** / HTML). Where **line breaks or spacing** inside the fence disagree, fix the Markdown.

**Incremental:** Per **shared**, fix fences **block by block** (each triple-backtick fenced region), then sweep the file for any missed or broken fences.

**Phase: code** — Fix all **fenced code blocks** (triple backticks) in **`<stem>.md`**.

- Do **not** change **inline** code (single backticks); leave as-is.
- Every fence opens with a line of three grave accents (U+0060) and closes with the same on its own line.
- Add a **language tag** after the opening fence when obvious from context (`cpp`, `c`, `sh`, `bash`, `cmake`, `json`, etc.). If unknown, use a bare fence with no language rather than guessing.

**Line breaks and spacing (PDF / excerpt):** First-pass conversion often **collapses** a multi-line listing into **one long line** inside a fence. That is wrong when the **source** shows multiple lines.

- Use **`<stem>.layout.json`** (and `source.pdf` if needed): for each code-like / monospace region, **preserve the line breaks** implied by **separate text lines** in the excerpt (each block line or logical line from the PDF). **Do not** join those lines into a single wrapped line unless the excerpt is genuinely one line.
- **Preserve meaningful horizontal spacing** inside a line when the excerpt shows indentation, alignment, or spaces between tokens that matter for reading the sample (e.g. column-aligned snippets). Do not normalize away spaces that exist in the source just to “compact” the code.
- If the excerpt shows **one** physical line but soft-wraps in the PDF, you may keep one line in Markdown; if it shows **distinct** lines (different `lines` entries or clear vertical breaks), reflect that with **newline characters** inside the fence.

**HTML:** Prefer `<pre>`, `<code>`, and whitespace in `source.html` — preserve newlines and spaces from the DOM when mapping into a fenced block.

- If fences are missing or a code block was merged with prose, repair structure only.
- Preserve all non–code-block text exactly as-is.


<!-- validate -->
Validate fenced blocks in the **Agent Output to Review** (full document).

**PDF excerpt:** Pass when each fenced block’s **line structure** and **spacing** match the monospace / code region in the layout (multiple excerpt lines → multiple lines in the fence unless the source is truly one line). **Fail** if a block was **collapsed to one line** when the excerpt shows **several** lines, or if code text was rewritten. Allow only minor wrap differences already delegated to other phases if explicitly noted there.

**No excerpt:** Pass only if every fence opens and closes correctly and language tags are present when the rules require them (see fix section).

Inline backticks are out of scope for this phase.

If all applicable checks pass, return {"pass": true, "reason": "ok"}.
