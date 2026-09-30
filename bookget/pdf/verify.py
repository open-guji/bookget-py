"""Post-build verification with PyMuPDF (optional dependency).

Checks that every page image is embedded byte-identical and in order, and
that no page came out blank (a LaTeX layout failure mode)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def verify_pdf(pdf_path, image_files: List[Path]) -> Optional[Tuple[bool, str, int, int]]:
    """(ok, message, page_count, image_pages) or None when PyMuPDF is not installed."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf      # older package name
        except ImportError:
            return None
    d = pymupdf.open(str(pdf_path))
    img_pages = [i for i in range(d.page_count) if d[i].get_images()]
    blank = [i + 1 for i in range(d.page_count) if not d[i].get_images() and len(d[i].get_text().strip()) < 5]
    if blank:
        return False, f"blank pages {blank}", d.page_count, len(img_pages)
    n = len(image_files)
    # the native engine's sheet pages are rasterised JPEGs too: they may follow the
    # content pages, but the content pages must all be there, in order
    leading = img_pages[:n]
    contiguous = bool(leading) and leading == list(range(leading[0], leading[0] + n))
    if len(img_pages) < n or not contiguous:
        return False, f"{len(img_pages)} image pages, expected {n} leading content pages", d.page_count, len(img_pages)
    for i, f in zip(img_pages[:n], image_files):
        xref = d[i].get_images(full=True)[0][0]
        if hashlib.md5(d.xref_stream_raw(xref)).hexdigest() != hashlib.md5(Path(f).read_bytes()).hexdigest():
            return False, f"page {i + 1} image differs from {Path(f).name}", d.page_count, len(img_pages)
    return True, "OK", d.page_count, len(img_pages)
