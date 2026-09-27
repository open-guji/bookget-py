"""PDF assembly: lossless JPEG embedding with rich metadata.

- writer.py  minimal PDF writer (no third-party dependency): JPEG pages embedded
             as-is (DCTDecode), Info dictionary, XMP, outlines, page labels,
             embedded file attachments
- sheet.py   optional metadata sheet rendered to images with Pillow + a CJK font
- schema.py  the document description both engines render (NPM record / NPM
             work / generic)
- latex.py   LuaLaTeX engine (typeset form; needs TeX Live) — the form used for
             the NPM → Wikimedia Commons uploads
- verify.py  PyMuPDF check: images byte-identical and in order, no blank pages
- build.py   assemble a downloaded book directory (images/ + metadata.json) into
             pdf/<name>.pdf with either engine
"""

from .build import ENGINES, build_book_pdf, pdf_filename  # noqa: F401
from .schema import document_schema  # noqa: F401
from .writer import PdfWriter  # noqa: F401
