"""Paper conversion: PDF and HTML sources to Markdown (v1 PDF: docling → pdfplumber only)."""

from paper_tools.convert.output_naming import (
    ingestion_run_dir_name,
    safe_stem_from_url,
    unique_stem,
)
from paper_tools.convert.pdf_convert import convert_pdf_path_to_md_v1
from paper_tools.convert.html_convert import convert_html_file_to_md

__all__ = [
    "ingestion_run_dir_name",
    "safe_stem_from_url",
    "unique_stem",
    "convert_pdf_path_to_md_v1",
    "convert_html_file_to_md",
]
