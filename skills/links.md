---
skill: links
---

<!-- fix -->
**Compare then fix:** Contrast **`<stem>.md`** with **`pages[].links`** in `<stem>.layout.json` and/or **`href`s in `source.html`**. Where a link is missing, wrong, or plain text, fix the Markdown to match the excerpt.

**Incremental:** Per **shared**, reconcile links **page by page** or **section by section** against `<stem>.layout.json` / `source.html`, then verify **all** excerpt links are represented.

**Phase: links** — Fix hyperlinks in **`<stem>.md`**.

**Goal — exhaustive excerpt coverage:** Every link that appears in the **structural excerpt** for this paper must have a counterpart in the Markdown. Do **not** cherry-pick “important” links only — **include them all**, even if a URL looks odd, duplicated, or mistaken; fidelity to the excerpt beats guessing what “should” be linked.

**PDF `<stem>.layout.json`:** Each page has **`pages[].links`** (may be empty). Treat entries as two families:
- **External / URI links:** **`uri`** present (http, https, mailto, ftp, etc.) → use that string in Markdown (`[text](uri)` or `<uri>` autolink where GFM allows).
- **Internal / anchor-style links:** no **`uri`** (or internal **`dest_page`**, **`dest`**, in-document targets) → represent as GFM links using the same target the PDF encodes (e.g. `[text](#fragment)`, `[text](relative#anchor)`, or page-style targets you can infer from **`dest`** / **`dest_page`**). If the PDF only gives a destination and the visible label is ambiguous, still add the link and tie it to the closest matching layout **text** by **bbox** / reading order.

Use **`links`** together with **blocks** / **lines** (and **`bbox`**) to place each link beside the right visible text. Do **not** drop an excerpt link because it looks wrong — preserve it; you may still fix obvious **GFM syntax** errors (broken `[]()`, stray spaces).

**HTML `source.html`:** Collect **every** navigable `href` from the excerpt DOM (anchors `#…`, same-document paths, and external URLs). Each should appear as proper Markdown link markup with the **same** target string as in `href` (after normal resolution), unless the first-pass already matched.

- Use GFM: `[visible](url)` or autolinks `<https://…>` where appropriate.
- Repair broken bracket/parenthesis pairing or truncated URLs **only** when the excerpt clearly shows the full target.
- If plain text in `.md` should be linked per excerpt, convert to link form.
- **Do not invent** links that are **not** in the excerpt; **do not omit** links that **are** in the excerpt.
- Preserve all non-link text exactly as-is.


<!-- validate -->
Validate links in the **Agent Output to Review** against **full excerpt coverage**.

**HTML `source.html`:** Build the set of `href` values from the excerpt (including `#fragment` and relative links). Fail if any are missing from the Markdown as links with equivalent targets (allow harmless encoding/normalization differences).

**PDF:** Build the set of link records from **`pages[].links`**: every **`uri`** must appear somewhere in the Markdown with that exact URI string (unless the author clearly split one logical link across lines — then fail with a concrete `comments` item). Every internal link (**`dest_page`** / **`dest`** / no **`uri`**) must appear as an appropriate GFM link target consistent with the excerpt. Fail if any excerpt link has no plausible Markdown counterpart near the right content.

**Syntax:** Pass only if GFM link syntax is valid and the above completeness checks hold.

If all applicable checks pass, return {"pass": true, "reason": "ok"}.
