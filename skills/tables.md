---
skill: tables
---

<!-- fix -->
**Compare then fix:** Contrast each **pipe table** in **`<stem>.md`** with the excerpt (layout blocks / HTML table). Where **rows, columns, or cell text** disagree, fix the Markdown.

**Incremental:** Per **shared**, fix **one table at a time** in reading order, then confirm every pipe table in the file was checked against the excerpt.

**Phase: tables** — Fix **GFM pipe tables** in **`<stem>.md`**.

**Logical rows vs pipe rows:** PDF tables often wrap; aim for **one logical row** per Markdown row. Merge wrap continuations into the same cell (space or `<br>`). Do not add extra rows that only continue text from the row above.

**Merging:** If a row has empty middle cells and the next row continues the last column mid-sentence, merge into the previous row’s cell.

**Columns:** Every row must have the same number of `|` columns. Pad with a single empty cell only when that cell is truly empty in the source.

**`<stem>.layout.json` (PDF):** Use block positions to infer **how many logical rows** and **columns** the source table has. Do not invent headers or cells not supported by the excerpt.

**No excerpt:** Add `| --- |` separator when the table clearly has a header row; otherwise keep the first row as data if that matches the visual.

Preserve all non-table content exactly as-is.


<!-- validate -->
Validate tables in the **Agent Output to Review**.

**Layout excerpt:** Pass when row/column structure and cell text match the source tables implied by the excerpt. Fail on invented rows/columns or “normalized away” merge errors.

**No excerpt:** Pass if column counts match on every row and continuation rows are merged sensibly.

If all applicable checks pass, return {"pass": true, "reason": "ok"}.
