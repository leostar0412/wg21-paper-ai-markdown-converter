"""PDF → Markdown (v1): docling → pdfplumber only (no vision/OpenRouter)."""

from __future__ import annotations

import logging
from pathlib import Path

try:
    from docling.document_converter import DocumentConverter

    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

logger = logging.getLogger(__name__)


def is_readable(text: str) -> bool:
    if not text or len(text.strip()) < 100:
        return False
    sample = text[:500]
    readable_chars = sum(
        1 for c in sample if c.isalnum() or c in " .,;:!?-\n\t()[]{}"
    )
    total_chars = len([c for c in sample if not c.isspace()])
    if total_chars == 0:
        return False
    if sample.count("/") > len(sample) * 0.1:
        return False
    return (readable_chars / total_chars) > 0.3


def convert_with_docling(pdf_path: Path) -> str | None:
    if not HAS_DOCLING:
        return None
    try:
        logger.info("Trying docling for %s", pdf_path)
        converter = DocumentConverter()
        result = converter.convert(str(pdf_path))
        md = result.document.export_to_markdown()
        if is_readable(md):
            logger.info("docling succeeded")
            return md
        logger.info("docling output not readable")
        return None
    except Exception as e:
        logger.warning("docling error: %s", e)
        return None


def convert_with_pdfplumber(pdf_path: Path) -> str | None:
    if not HAS_PDFPLUMBER:
        return None
    try:
        logger.info("Trying pdfplumber for %s", pdf_path)
        parts: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        if not parts:
            return None
        combined = "\n\n".join(parts)
        if is_readable(combined):
            logger.info("pdfplumber succeeded")
            return combined
        return None
    except Exception as e:
        logger.warning("pdfplumber error: %s", e)
        return None


def convert_pdf_path_to_md_v1(pdf_path: Path, output_md: Path) -> bool:
    """
    Convert a local PDF file to Markdown at *output_md*.
    Tries docling → pdfplumber only.
    """
    if not pdf_path.is_file():
        logger.error("PDF not found: %s", pdf_path)
        return False

    md: str | None = convert_with_docling(pdf_path)
    if md is None:
        md = convert_with_pdfplumber(pdf_path)

    if md is None:
        logger.error("All PDF extractors failed for %s", pdf_path)
        return False

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(md, encoding="utf-8")
    return True
