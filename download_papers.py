#!/usr/bin/env python3
"""Download papers from URLs into a folder (PDF or HTML). No Markdown conversion.

Uses the same ``--papers`` JSON shape and default ``--output-dir`` as
``wg21-paper-markdown-converter/url2md.py``. Prefer ``--folder`` as the
destination when matching :mod:`run_prompt` workflows (same path as workspace).

Example::

  python download_papers.py --folder ./papers --papers '{"papers": ["https://example.com/a.pdf"]}'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from paper_tools.url_download import PaperDownloadResult, download_papers, parse_papers_json

DEFAULT_OUTPUT_DIR = "converted"
DEFAULT_DOWNLOAD_LOG = "paper_download_log.json"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--papers",
        required=True,
        help='JSON string: {"papers": ["url1", "url2", ...]} (same as url2md.py).',
    )
    p.add_argument(
        "--folder",
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIR),
        help=(
            f"Directory to save downloaded files (default: {DEFAULT_OUTPUT_DIR}). "
            "Same as url2md --output-dir; --folder is an alias."
        ),
    )
    p.add_argument(
        "--fetch-timeout",
        type=int,
        default=60,
        help="HTTP timeout in seconds for each GET (default: 60).",
    )
    p.add_argument(
        "--log-json",
        type=Path,
        default=None,
        help=(
            f"Write a JSON summary next to downloads "
            f"(default: <output-dir>/{DEFAULT_DOWNLOAD_LOG}). "
            "Pass an absolute path to override."
        ),
    )
    p.add_argument(
        "--no-log-json",
        action="store_true",
        help="Do not write the JSON download log file.",
    )
    return p


def _write_log(path: Path, result: PaperDownloadResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_log_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    args = _build_parser().parse_args()
    out_dir: Path = args.output_dir.expanduser().resolve()

    try:
        urls = parse_papers_json(args.papers)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"ERROR: Invalid --papers value: {e}", file=sys.stderr)
        print(
            'Expected format: --papers \'{"papers": ["url1", "url2"]}\'',
            file=sys.stderr,
        )
        return 1

    result = download_papers(urls, out_dir, fetch_timeout=args.fetch_timeout)

    for item in result.items:
        status = "OK" if item.success else "FAIL"
        rel = item.path or "—"
        print(f"[{status}] {item.file_type:5} {item.url} -> {rel}")
        if not item.success and item.error:
            print(f"       {item.error}", file=sys.stderr)

    if not args.no_log_json:
        log_path = args.log_json
        if log_path is None:
            log_path = out_dir / DEFAULT_DOWNLOAD_LOG
        else:
            log_path = log_path.expanduser().resolve()
        _write_log(log_path, result)
        print(f"Wrote download log -> {log_path}", file=sys.stderr)

    all_ok = all(i.success for i in result.items)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
