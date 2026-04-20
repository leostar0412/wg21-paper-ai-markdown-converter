"""HTML → Markdown via Pandoc (ported from wg21-paper-markdown-converter/html_converter.py)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pypandoc
from lxml import html as lxml_html

_pandoc_ensured = False


def _pandoc_bundle_dir() -> Path:
    """Stable, user-writable install location (avoids relying on ~/Applications/pandoc alone)."""
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "wg21-paper-tools" / "pandoc"


def _ensure_pandoc() -> None:
    """Use system pandoc if present; otherwise download a bundled binary (pypandoc)."""
    global _pandoc_ensured
    if _pandoc_ensured:
        return
    bundle = _pandoc_bundle_dir()
    bundle.mkdir(parents=True, exist_ok=True)
    # Drop stale cached path if a previous install left a missing binary.
    pypandoc.clean_pandocpath_cache()
    pypandoc.ensure_pandoc_installed(targetfolder=str(bundle))
    _pandoc_ensured = True


_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _preprocess_html_content(html_content: str) -> str:
    html_clean = re.sub(r"<\?xml[^>]*\?>", "", html_content, flags=re.IGNORECASE)
    html_clean = re.sub(r"<!DOCTYPE[^>]*>", "", html_clean, flags=re.IGNORECASE)

    parser = lxml_html.HTMLParser(encoding="utf-8", recover=True)
    try:
        html_bytes = html_clean.encode("utf-8")
        tree = lxml_html.fromstring(html_bytes, parser=parser)
        result = lxml_html.tostring(tree, pretty_print=True, encoding="utf-8")
        return result.decode("utf-8")
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("lxml preprocessing failed: %s", e)
        return html_content


def preprocess_html_for_metadata(html_content: str) -> str:
    body_start_match = re.search(r"<body\b[^>]*>", html_content, re.IGNORECASE)
    if not body_start_match:
        return _preprocess_html_content(html_content)

    body_open = body_start_match.group(0)
    body_start_pos = body_start_match.end()

    body_close_match = re.search(r"</body>", html_content[body_start_pos:], re.IGNORECASE)
    if body_close_match:
        body_end_pos = body_start_pos + body_close_match.start()
        body_content = html_content[body_start_pos:body_end_pos]
        body_close = "</body>"
        remaining_after_body = html_content[body_start_pos + body_close_match.end() :]
    else:
        body_content = html_content[body_start_pos:]
        body_close = "</body>"
        remaining_after_body = ""

    main_start_match = re.search(r"<main\b[^>]*>", body_content, re.IGNORECASE)
    if not main_start_match:
        return _preprocess_html_content(html_content)

    main_open = main_start_match.group(0)
    main_start_pos = main_start_match.end()

    main_close_match = re.search(r"</main>", body_content[main_start_pos:], re.IGNORECASE)
    if main_close_match:
        main_end_pos = main_start_pos + main_close_match.start()
        main_content = body_content[main_start_pos:main_end_pos]
        main_close = "</main>"
    else:
        main_content = body_content[main_start_pos:]
        main_close = "</main>"

    main_start = main_start_match.start()
    if main_close_match:
        main_end = main_start_pos + main_close_match.end()
    else:
        main_end = len(body_content)

    before_main = body_content[:main_start].strip()
    after_main = body_content[main_end:].strip()

    if not before_main and not after_main:
        return _preprocess_html_content(html_content)

    parts = []
    if before_main:
        parts.append(before_main)
    parts.append(main_content)
    if after_main:
        parts.append(after_main)

    new_main_tag = main_open + "\n" + "\n".join(parts) + "\n" + main_close
    new_html = (
        html_content[: body_start_match.start()]
        + body_open
        + "\n"
        + new_main_tag
        + "\n"
        + body_close
        + remaining_after_body
    )
    return _preprocess_html_content(new_html)


def _convert_html_tables_to_markdown(text: str) -> str:
    table_pattern = r"([^\n]*?)<table[^>]*>(.*?)</table>"

    def convert_table(match):
        prefix = match.group(1)
        table_html = match.group(2)

        table_html = re.sub(r"<colgroup>.*?</colgroup>", "", table_html, flags=re.DOTALL)
        table_html = re.sub(r"<col[^>]*/?>", "", table_html)

        rows = []

        thead_match = re.search(r"<thead>(.*?)</thead>", table_html, re.DOTALL)
        if thead_match:
            header_row = re.search(r"<tr[^>]*/?>(.*?)</tr>", thead_match.group(1), re.DOTALL)
            if header_row:
                cells = re.findall(r"<t[hd][^>]*/?>(.*?)</t[hd]>", header_row.group(1), re.DOTALL)
                cleaned = []
                for cell in cells:
                    cell = re.sub(r"<code[^>]*/?>", "`", cell)
                    cell = re.sub(r"</code>", "` ", cell)
                    cell = re.sub(r"<[^/>]+>", "", cell)
                    cell = re.sub(r"</[^>]+>", "", cell)
                    cleaned.append(" ".join(cell.split()).strip())
                rows.append(cleaned)

        tbody_match = re.search(r"<tbody[^>]*/?>(.*?)</tbody>", table_html, re.DOTALL)
        if tbody_match:
            for row_html in re.findall(r"<tr[^>]*/?>(.*?)</tr>", tbody_match.group(1), re.DOTALL):
                cells = re.findall(r"<t[hd][^>]*/?>(.*?)</t[hd]>", row_html, re.DOTALL)
                cleaned = []
                for cell in cells:
                    cell = re.sub(r"<code[^>]*/?>", "`", cell)
                    cell = re.sub(r"</code>", "` ", cell)
                    cell = re.sub(r"<[^/>]+>", "", cell)
                    cell = re.sub(r"</[^>]+>", "", cell)
                    cleaned.append(" ".join(cell.split()).strip())
                if cleaned:
                    rows.append(cleaned)

        if not rows:
            all_rows = re.findall(r"<tr[^>]*/?>(.*?)</tr>", table_html, re.DOTALL)
            for row_html in all_rows:
                cells = re.findall(r"<t[hd][^>]*/?>(.*?)</t[hd]>", row_html, re.DOTALL)
                cleaned = []
                for cell in cells:
                    cell = re.sub(r"<code[^>]*/?>", "`", cell)
                    cell = re.sub(r"</code>", "` ", cell)
                    cell = re.sub(r"<[^/>]+>", "", cell)
                    cell = re.sub(r"</[^>]+>", "", cell)
                    cleaned.append(" ".join(cell.split()).strip())
                if cleaned:
                    rows.append(cleaned)

        if not rows:
            return match.group(0)

        num_cols = len(rows[0])
        if num_cols == 0:
            return match.group(0)

        lines = []
        lines.append("| " + " | ".join(rows[0]) + " |")
        lines.append("| " + " | ".join(["---"] * num_cols) + " |")
        for row in rows[1:]:
            while len(row) < num_cols:
                row.append(" ")
            lines.append("| " + " | ".join(row[:num_cols]) + " |")

        table_md = "\n".join(lines)
        if prefix:
            table_md = "\n".join(prefix + line for line in lines)

        return table_md

    return re.sub(table_pattern, convert_table, text, flags=re.DOTALL | re.IGNORECASE)


def post_process_markdown(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = text.split("\n")
    if (
        len(lines) > 2
        and lines[0].strip().startswith("|")
        and "---" not in lines[0]
        and lines[1].strip() == ""
        and len(lines) > 2
        and "---" in lines[2]
    ):
        if len(lines) > 3 and lines[3].strip().startswith("|"):
            lines = lines[1:]
        else:
            lines = lines[3:]

    fixed = []
    i = 0
    while i < len(lines):
        if (
            i < len(lines) - 2
            and lines[i].strip().startswith("|")
            and "---" in lines[i + 1]
        ):
            fixed.append(lines[i])
            fixed.append(lines[i + 1])
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                fixed.append(lines[i])
                i += 1
            continue
        fixed.append(lines[i])
        i += 1
    text = "\n".join(fixed)

    text = re.sub(r"^(\s*)\d+\.\s+(\[)", r"\1- \2", text, flags=re.MULTILINE)

    text = re.sub(r'(#{1,6})\s*<a[^>]*class="anchor"[^>]*>(?:<[^>]+>)*</a>\s*', r"\1 ", text)
    text = re.sub(r'(#{1,6})\s*<a[^>]*id="user-content-[^"]*"[^>]*>(?:<[^>]+>)*</a>\s*', r"\1 ", text)
    text = re.sub(r'(#{1,6})\s*<a[^>]*href="#[^"]*"[^>]*>(?:<[^>]+>)*</a>\s*', r"\1 ", text)
    text = re.sub(r"(#{1,6})\s*<a[^>]*>.*?</a>\s*", r"\1 ", text, flags=re.DOTALL)

    text = re.sub(r"<div[^>]*>\s*", "", text)
    text = re.sub(r"\s*</div>", "", text)
    text = re.sub(r"<span[^>]*>\s*", "", text)
    text = re.sub(r"\s*</span>", "", text)

    text = re.sub(r"<ins[^>]*>", "", text)
    text = re.sub(r"</ins>", "", text)
    text = re.sub(r"<del[^>]*>", "~~", text)
    text = re.sub(r"</del>", "~~ ", text)
    text = re.sub(r"<u[^>]*>", "", text)
    text = re.sub(r"</u>", "", text)
    text = re.sub(r"<tt[^>]*>", "`", text)
    text = re.sub(r"</tt>", "` ", text)
    text = re.sub(r"<code[^>]*>([^<`]+)(?![^<]*</code>)", r"`\1` ", text)
    text = re.sub(r"<code[^>]*>", "`", text)
    text = re.sub(r"</code>", "` ", text)
    text = re.sub(r"``([^`]+)``", r"`\1`", text)
    text = re.sub(r"<strong[^>]*>", "**", text)
    text = re.sub(r"</strong>", "** ", text)
    text = re.sub(r"<b\b[^>]*>", "**", text)
    text = re.sub(r"</b>", "** ", text)
    text = re.sub(r"<em[^>]*>", "*", text)
    text = re.sub(r"</em>", "* ", text)
    text = re.sub(r"<i[^>]*>", "*", text)
    text = re.sub(r"</i>", "* ", text)
    text = re.sub(r"``([^`]+)``", r"`\1`", text)

    text = re.sub(r"```\n\n+", "```\n", text)
    text = re.sub(r"\n\n+```", "\n```", text)

    text = re.sub(r"\n\n+> ", "\n\n> ", text)

    lines = text.split("\n")
    filtered = [line for line in lines if not re.match(r"^#{1,6}\s*$", line)]
    text = "\n".join(filtered)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n{2,}(#{1,6}\s)", r"\n\n\1", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = text.lstrip("\n")

    text = _convert_html_tables_to_markdown(text)

    text = re.sub(r'\\\[<a href="([^"]+)"[^>]*>([^<]+)</a>\\\]', r"[[\2](\1)]", text)

    return text.rstrip() + "\n"


def convert_html_file_to_md(html_path: Path, output_path: Path) -> bool:
    """Read local HTML file, convert to GFM Markdown, write *output_path*."""
    try:
        html_content = html_path.read_text(encoding="utf-8")
    except OSError as e:
        import logging

        logging.getLogger(__name__).error("Read failed %s: %s", html_path, e)
        return False

    try:
        html_content = preprocess_html_for_metadata(html_content)

        _ensure_pandoc()
        output = pypandoc.convert_text(
            html_content,
            "gfm",
            format="html",
            extra_args=["--wrap=none", "--preserve-tabs", "--standalone"],
        )
        output = post_process_markdown(output)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        return True

    except Exception as e:
        import logging

        logging.getLogger(__name__).error("Pandoc conversion failed for %s: %s", html_path, e)
        return False


__all__ = ["convert_html_file_to_md", "_FETCH_HEADERS"]
