"""Download papers from URLs into a folder (PDF or HTML), without conversion.

Aligned with ``wg21-paper-markdown-converter/url2md.py`` for URL typing and fetch behavior.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import requests

# Same as html_converter._FETCH_HEADERS (wg21-paper-markdown-converter).
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def detect_type(url: str) -> str:
    """Return ``\"pdf\"`` or ``\"html\"`` based on URL suffix then Content-Type (HEAD)."""
    parsed = urlparse(url)
    if parsed.path.lower().endswith(".pdf"):
        return "pdf"
    try:
        head = requests.head(url, allow_redirects=True, timeout=15)
        ct = head.headers.get("Content-Type", "").lower()
        if "pdf" in ct:
            return "pdf"
    except Exception:
        pass
    return "html"


def url_to_download_basename(url: str, file_type: str) -> str:
    """Safe filename with ``.pdf`` or ``.html`` (same stem rules as ``output_naming.url_to_filename``)."""
    parsed = urlparse(url)
    stem = Path(parsed.path).stem or "index"
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in stem)
    ext = ".pdf" if file_type == "pdf" else ".html"
    return f"{safe}{ext}"


def _unique_path(output_dir: Path, basename: str) -> Path:
    p = output_dir / basename
    if not p.exists():
        return p
    stem = Path(basename).stem
    suf = Path(basename).suffix
    n = 2
    while True:
        cand = output_dir / f"{stem}_{n}{suf}"
        if not cand.exists():
            return cand
        n += 1


def _validate_pdf_payload(path: Path) -> tuple[bool, str]:
    try:
        raw = path.read_bytes()
    except OSError as e:
        return False, str(e)
    if len(raw) < 32:
        return False, f"file too small ({len(raw)} bytes)"
    if not raw.startswith(b"%PDF"):
        head = raw[:800].lower()
        if b"<html" in head or b"<!doctype" in head:
            return False, "not a PDF (response looks like HTML — check URL or auth)"
        return False, "missing PDF %PDF header (not a PDF or truncated download)"
    return True, ""


def _download_pdf(url: str, dest: Path, *, timeout: int) -> tuple[bool, str | None, int]:
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        ok, msg = _validate_pdf_payload(dest)
        if not ok:
            dest.unlink(missing_ok=True)
            return False, msg, 0
        return True, None, dest.stat().st_size
    except Exception as e:
        dest.unlink(missing_ok=True)
        return False, str(e), 0


def _download_html(url: str, dest: Path, *, timeout: int) -> tuple[bool, str | None, int]:
    try:
        response = requests.get(url, headers=_FETCH_HEADERS, timeout=timeout)
        response.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = response.text
        dest.write_text(text, encoding="utf-8")
        return True, None, dest.stat().st_size
    except Exception as e:
        dest.unlink(missing_ok=True)
        return False, str(e), 0


@dataclass
class PaperDownloadItem:
    url: str
    file_type: str
    path: str | None = None
    success: bool = False
    bytes_written: int = 0
    duration_ms: int = 0
    error: str | None = None


@dataclass
class PaperDownloadResult:
    output_dir: str
    items: list[PaperDownloadItem] = field(default_factory=list)
    total_wall_ms: int = 0

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "log_version": 1,
            "output_dir": self.output_dir,
            "total_wall_ms": self.total_wall_ms,
            "items": [
                {
                    "url": i.url,
                    "file_type": i.file_type,
                    "path": i.path,
                    "success": i.success,
                    "bytes": i.bytes_written,
                    "duration_ms": i.duration_ms,
                    "error": i.error,
                }
                for i in self.items
            ],
        }


def download_papers(
    urls: list[str],
    output_dir: Path,
    *,
    fetch_timeout: int = 60,
) -> PaperDownloadResult:
    """Download each URL to *output_dir* as ``.pdf`` or ``.html`` based on :func:`detect_type`."""
    out = output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    items: list[PaperDownloadItem] = []

    for raw in urls:
        url = raw.strip()
        if not url:
            continue
        ft = detect_type(url)
        basename = url_to_download_basename(url, ft)
        dest = _unique_path(out, basename)
        item = PaperDownloadItem(url=url, file_type=ft)
        t1 = time.monotonic()
        if ft == "pdf":
            ok, err, nbytes = _download_pdf(url, dest, timeout=fetch_timeout)
        else:
            ok, err, nbytes = _download_html(url, dest, timeout=fetch_timeout)
        item.duration_ms = int((time.monotonic() - t1) * 1000)
        item.success = ok
        item.bytes_written = nbytes
        item.path = dest.name if ok else None
        item.error = err
        items.append(item)

    wall = int((time.monotonic() - t0) * 1000)
    return PaperDownloadResult(output_dir=str(out), items=items, total_wall_ms=wall)


def download_into_paper_folder(
    url: str,
    paper_dir: Path,
    *,
    fetch_timeout: int = 60,
) -> tuple[Literal["pdf", "html"], bool, str | None]:
    """
    Download *url* into *paper_dir* as ``source.pdf`` or ``source.html``.
    Returns ``(file_type, success, error_message)``.
    """
    paper_dir.mkdir(parents=True, exist_ok=True)
    ft = detect_type(url)
    if ft == "pdf":
        dest = paper_dir / "source.pdf"
        ok, err, _ = _download_pdf(url, dest, timeout=fetch_timeout)
        return "pdf", ok, err
    dest = paper_dir / "source.html"
    ok, err, _ = _download_html(url, dest, timeout=fetch_timeout)
    return "html", ok, err


def parse_papers_json(papers_arg: str) -> list[str]:
    """Parse ``--papers`` the same way as ``url2md.py``."""
    payload = json.loads(papers_arg)
    urls: list[str] = payload["papers"]
    if not isinstance(urls, list) or not urls:
        raise ValueError("'papers' must be a non-empty list of URLs")
    return [str(u).strip() for u in urls if str(u).strip()]
