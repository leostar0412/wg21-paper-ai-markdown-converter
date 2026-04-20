"""PyMuPDF layout excerpt JSON for PDF papers (HTML uses ``source.html`` as excerpt)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF

    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


def _norm_bbox(bbox: Any) -> list[float]:
    if not bbox:
        return []
    try:
        return [round(float(x), 4) for x in bbox]
    except (TypeError, ValueError):
        return []


def _serialize_span(span: dict[str, Any]) -> dict[str, Any]:
    """One text span with font metrics and style hints (PyMuPDF ``get_text('dict')``)."""
    out: dict[str, Any] = {
        "text": span.get("text", ""),
        "bbox": _norm_bbox(span.get("bbox")),
        "font": span.get("font") or "",
        "size": round(float(span.get("size") or 0), 4),
        "flags": int(span.get("flags", 0)),
    }
    if "color" in span and span["color"] is not None:
        out["color"] = span["color"]
    fl = out["flags"]
    # PyMuPDF / MuPDF: TEXT_FONT_* bit masks (see pymupdf fitz module)
    fm = fitz
    out["superscript"] = bool(fl & getattr(fm, "TEXT_FONT_SUPERSCRIPT", 1))
    out["italic"] = bool(fl & getattr(fm, "TEXT_FONT_ITALIC", 2))
    out["serif"] = bool(fl & getattr(fm, "TEXT_FONT_SERIFED", 4))
    out["monospace"] = bool(fl & getattr(fm, "TEXT_FONT_MONOSPACED", 8))
    out["bold"] = bool(fl & getattr(fm, "TEXT_FONT_BOLD", 16))
    fn = out["font"].lower()
    if not out["bold"] and any(x in fn for x in ("bold", "black", "heavy")):
        out["bold"] = True
    if not out["italic"] and any(x in fn for x in ("italic", "oblique")):
        out["italic"] = True
    return out


def _serialize_page_links(page: Any) -> list[dict[str, Any]]:
    """Extract URI / internal links from a PDF page for JSON (PyMuPDF ``get_links()``)."""
    raw = page.get_links() or []
    out: list[dict[str, Any]] = []
    for li in raw:
        entry: dict[str, Any] = {}
        k = li.get("kind")
        if k is not None:
            entry["kind"] = k
        rect = li.get("from")
        if rect is not None:
            try:
                entry["bbox"] = [
                    round(float(rect.x0), 4),
                    round(float(rect.y0), 4),
                    round(float(rect.x1), 4),
                    round(float(rect.y1), 4),
                ]
            except (AttributeError, TypeError, ValueError):
                entry["bbox"] = []
        uri = li.get("uri")
        if uri:
            entry["uri"] = uri
        # Internal go-to: destination page index is 0-based in PyMuPDF
        if "page" in li and li["page"] is not None:
            try:
                entry["dest_page"] = int(li["page"]) + 1
            except (TypeError, ValueError):
                pass
        dest = li.get("to")
        if dest is not None and not uri:
            if isinstance(dest, (str, int, float)):
                entry["dest"] = dest
            elif isinstance(dest, (list, tuple)):
                entry["dest"] = list(dest)
            else:
                entry["dest"] = str(dest)
        fn = li.get("file")
        if fn:
            entry["file"] = str(fn)
        out.append(entry)
    return out


def write_pdf_layout_json(pdf_path: Path, output_json: Path) -> bool:
    """
    Write a compact layout excerpt: per-page text blocks with bounding boxes,
    per-line **spans** with **font name**, **size**, **flags**, and derived
    **bold** / **italic** / **monospace** / etc., plus per-page **links** (URIs
    and internal destinations). Links and spans come from PyMuPDF; some PDFs
    simulate bold without setting flags — font-name heuristics are applied as a
    fallback.

    Returns False if PyMuPDF is unavailable or the PDF cannot be read.
    """
    if not HAS_PYMUPDF:
        logger.error("PyMuPDF (pymupdf) not installed — cannot write layout excerpt")
        return False
    if not pdf_path.is_file():
        return False

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning("Could not open PDF for layout: %s", e)
        return False

    pages_out: list[dict[str, Any]] = []
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            blocks_raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
            blocks: list[dict[str, Any]] = []
            for b in blocks_raw:
                if b.get("type") != 0:
                    continue
                bbox = b.get("bbox")
                lines_out: list[dict[str, Any]] = []
                for line in b.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(s.get("text", "") for s in spans).strip()
                    span_objs = [_serialize_span(s) for s in spans]
                    if text:
                        line_entry: dict[str, Any] = {"text": text}
                        if span_objs:
                            line_entry["spans"] = span_objs
                        lines_out.append(line_entry)
                if lines_out:
                    blocks.append({"bbox": list(bbox) if bbox else [], "lines": lines_out})
            links_out = _serialize_page_links(page)
            page_entry: dict[str, Any] = {
                "page": page_index + 1,
                "blocks": blocks,
                "links": links_out,
            }
            pages_out.append(page_entry)
    finally:
        doc.close()

    payload = {
        "source_pdf": pdf_path.name,
        "page_count": len(pages_out),
        "pages": pages_out,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return True


def html_excerpt_manifest_note() -> dict[str, str]:
    """Minimal pointer for HTML papers (no separate excerpt file on disk)."""
    return {"type": "html", "note": "Structural excerpt is source.html in this folder."}
