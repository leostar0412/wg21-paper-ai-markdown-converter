"""Safe folder / file stems from URLs (aligned with wg21 output_naming)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse


def safe_stem_from_url(url: str) -> str:
    """Derive a safe basename stem from the URL path (no extension)."""
    parsed = urlparse(url)
    stem = Path(parsed.path).stem or "index"
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in stem)


def unique_stem(url: str, used: set[str]) -> str:
    """Return a stem not yet in *used*; append ``_2``, ``_3``, … if needed."""
    base = safe_stem_from_url(url)
    if base not in used:
        used.add(base)
        return base
    n = 2
    while True:
        cand = f"{base}_{n}"
        if cand not in used:
            used.add(cand)
            return cand
        n += 1


def ingestion_run_dir_name(papers: list[str], ts: str) -> str:
    """
    Folder name under ``temp/``: ``ingestion_run_<id>_<UTC>_<url_stem>``.

    *ts* should be a UTC timestamp string (e.g. ``%Y%m%dT%H%M%SZ``).
    The 12-char *id* is the leading hex of SHA-256 of ``ts`` and *url_stem*.
    Uses the first non-empty paper URL for *url_stem* (safe for paths, max 48 chars).
    """
    first = next((str(p).strip() for p in papers if str(p).strip()), "")
    slug = safe_stem_from_url(first) if first else "run"
    if not slug:
        slug = "index"
    if len(slug) > 48:
        slug = slug[:48].rstrip("_")
    uid = hashlib.sha256(f"{ts}\0{slug}".encode("utf-8")).hexdigest()[:12]
    return f"ingestion_run_{uid}_{ts}_{slug}"
