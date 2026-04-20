---
skill: headings
---

<!-- fix -->
**Compare then fix:** Contrast **`<stem>.md`** with the excerpt (**`<stem>.layout.json`** or **`source.html`**). Where **title or heading depth** disagrees with the excerpt, correct the Markdown.

**Incremental:** Per **shared**, fix headings **section by section** (e.g. each `##` / `###` region in reading order), then confirm **every** heading in the file matches the excerpt.

**Phase: headings** — Fix the heading hierarchy in **`<stem>.md`** (see Workspace + Task context in the user message). Ground truth: **`<stem>.layout.json`** (PDF) or **`source.html`** (HTML).

### Document title

- Exactly **one** level-1 heading (`#`) — the paper title — and it must be the **first** heading in the file.
- **Split titles:** If the converter produced two `##` lines for one title (e.g. a line break after “metafunction -” and a second line with the rest of the name), **merge** into a single `#` line. Keep escapes and punctuation as in the source (e.g. `is\_structural\_type`).
- **Numbered sections** in the body (`1.`, `2.`, `3.1`, …) use **`##` … `######` only**, never `#`.

### Section numbering vs Markdown depth

- **Outline gaps** (e.g. `3.1.2` then `3.3` with no `3.2` in the title text) are **normal** for WG papers — do not “fix” missing numbers in the outline.
- **Match source hierarchy, not a fixed `##`-only pattern.** Section numbers like `3` and `3.1` might map to **`##` / `##`**, **`##` / `###`**, **`###` / `###`**, etc. — any valid ATX combo from `#` … `######` except `#` for body sections.
- **Same visual / structural rank in the source → same Markdown depth:** If **3** and **3.1** use the **same** heading style in the PDF/HTML (same size, same weight, same heading tag level relative to each other), use the **same ATX depth** for both (e.g. both `##`, or both `###`). Do **not** force `3.1` deeper **only** because its number has a dot — check whether the source actually nests it visually under **3** or treats it as a sibling subsection line.
- **Different visual / structural rank → different depth:** If the source clearly makes one title **larger or bolder** than another, or uses a **lower** `<hN>` number in HTML, reflect that with **different** ATX levels (`##` vs `###` vs `####`, etc.).
- **Ground truth:** Use **`<stem>.layout.json`** (block order, bbox, any typography cues) and **`source.html`** (`<h1>`–`<h6>`). When unsure, prefer **matching PDF/HTML** over inventing extra nesting or flattening real hierarchy.

### Visual style: true headings vs body text

- In the **source**, real section titles are almost always **typographically distinct** from body copy: **larger type and/or bold** (or an actual **HTML heading** element).
- **HTML (`source.html`):** A line must **not** stay as `#`…`######` if it is **only** a paragraph or list item in the DOM. If the first-pass put `## …` on text that is plain `<p>` / `<li>` with **the same weight/size as surrounding body text** (not `<h1>`–`<h6>`, not a title-style `<strong>` spanning the whole line), **remove** the ATX heading and keep that text as **normal body** (plain paragraph or appropriate list markup — list fixes may be another phase). Conversely, text that **is** an `<h1>`–`<h6>` or clearly styled as the paper’s section title **must** be represented with the matching ATX level.
- **PDF (`<stem>.layout.json`):** Lines may include **`spans`** with **`size`**, **`bold`**, **`italic`**, **`font`**. Prefer those cues plus **bbox** position: **do not** keep Markdown headings for lines whose **spans** match **body** size/weight, or demote when only numbering makes a line look like a title.
- **Rule of thumb:** If something is tagged as a heading in Markdown but the **source shows it as ordinary body typography** (not big, not bold, not an `<h*>`), **demote** it to **normal text** — not a heading.

### PDF layout JSON

- Use **block order** and **bbox** (vertical position) to infer **reading order** and whether a block is a **title** vs paragraph. Do not merge or split heading lines against the source.

### HTML

- Prefer **`source.html`** heading tags (`<h1>`…`<h6>`) for level and order when they conflict with a bad Markdown conversion. Use **bold/size** and heading tags together with the **Visual style** rules above.

### Markup rules

- **ATX only** (`#` … `######`). No setext underlines.
- Every `##`…`######` marker starts at the **beginning of its own line**. If a marker appears at the **end** of a paragraph line, **move** it to the **next** line with the heading text.
- **Link-only lines** that act as sub-headings (e.g. a Godbolt link under a proof-of-concept section) should be **one level deeper** than their parent **when the source nests them** — e.g. `####` under `###` when that matches the excerpt; do not assume the parent is always `##`.
- Preserve all **non-heading** body text exactly as-is (hyphenation, code, and typos outside headings are other phases).

<!-- validate -->

Validate the **full Markdown** under **Agent Output to Review** for this phase.

**Title rule:**

- Exactly one `#` heading, first heading in the document, document title.
- No numbered main section uses `#`.

**Contents (if present):** Pass when there is at most one `## Contents` (or equivalent) and the TOC list **matches** the main body section headings in **order** — fail on duplicate `Contents` headings or a TOC that **contradicts** the actual section headings (wrong numbering or duplicate section numbers for different titles).

**Depth vs source:** Pass when numbered sections at **3** vs **3.1** (and similar) use **the same ATX depth iff** the excerpt shows **the same** title style/rank for both; **fail** if Markdown invents extra nesting or flattens a clear parent/child distinction from PDF/HTML.

**Revision history:** Pass when **From version N** lines use a **deeper** heading level than `## 1. Revision History` (e.g. `###`), not sibling `##` at the same depth as section 1, unless the excerpt proves otherwise.

**Inline heading rule:** Fail if any `##`…`######` marker is not at the start of a line.

**PDF layout JSON:** Pass when heading **sequence** and **titles** match the excerpt’s title-like blocks (allow imperfect depth if structure matches). Fail if a heading was invented, dropped, or re-leveled against the source.

**HTML:** Pass when heading **levels and order** match `source.html`, **and** every `##`…`######` corresponds to an `<h1>`–`<h6>` or clearly **title-styled** text (larger and/or bold vs body). **Fail** if a Markdown heading wraps **plain body** typography (same as surrounding paragraphs, not `<h*>`). Demoting spurious headings to normal paragraphs is a **pass** when that matches the source.

**No excerpt:** Pass only if: one `#` title; no **accidental** skipped Markdown levels (e.g. `##` → `####` with no `###` unless the document truly has only those ranks); ATX-only. Flat same-depth siblings are **allowed** when consistent.

If all applicable checks pass, return {"pass": true, "reason": "ok"}.
