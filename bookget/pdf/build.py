"""Assemble a downloaded book directory into one archival PDF.

Input layout (what ``bookget download`` produces)::

    <book_dir>/
      metadata.json            BookMetadata.to_dict()
      raw.<site_id>.json       adapter's raw record(s) (optional; drives the sheet)
      images/*.jpg             page images, sorted by filename

Two engines render the same document schema (see schema.py):

* ``native``  pure Python: JPEGs embedded verbatim, Info/XMP, bookmarks, page
              labels, attachments, and a metadata sheet rasterised with Pillow
              (skipped when no CJK font is available)
* ``latex``   LuaLaTeX: the same, with a typeset form of selectable text — the
              form used for the NPM → Wikimedia Commons uploads. Needs TeX Live.

Output: ``<book_dir>/pdf/<file_stem>.pdf``.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .schema import TOOL_URL, document_schema, list_images
from .sheet import Section, SheetSpec, find_cjk_font, render_sheet
from .verify import verify_pdf
from .writer import Attachment, Outline, PdfWriter

logger = logging.getLogger(__name__)
ENGINES = ("native", "latex")


def pdf_filename(md: Dict, prefix: str = "") -> str:
    from .schema import file_stem
    return file_stem(md, prefix) + ".pdf"


def _as_jpeg(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:2] == b"\xff\xd8":
        return data
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError(f"{path.name} is not a JPEG and Pillow is not installed (pip install bookget[pdf])")
    logger.warning(f"Re-encoding non-JPEG page {path.name} (quality 95)")
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


# ---------------------------------------------------------------- native sheet from the schema
def sheet_spec(m: Dict) -> SheetSpec:
    """Sheet content for the native engine: every schema section, then licence,
    image list and provenance — the same content the LaTeX form typesets."""
    sections: List[Section] = []
    for s in m["sections"]:
        en = s.get("title_en") or ""
        if s.get("fields"):
            fields = [(f["label_zh"] + (f" {f['label_en']}" if f.get("label_en") else ""), str(f["value"])) for f in s["fields"]]
            sections.append(Section(s["title_zh"], en, fields=fields, note=s.get("note") or ""))
        elif s.get("rows"):
            sections.append(Section(s["title_zh"], en, header=list(s["header_zh"]), rows=[list(map(str, r)) for r in s["rows"]],
                                    note=s.get("note") or ""))
        elif s.get("note"):
            sections.append(Section(s["title_zh"], en, note=s["note"]))
    lic = m["license"]
    if lic.get("image_license"):
        sections.append(Section("授權與引用", "License and attribution", fields=[(k, v) for k, v in [
            ("授權條款 License", f"{lic['image_license']}  {lic.get('image_license_url', '')}".strip()),
            ("圖檔層級 Image tier", lic.get("image_tier", "")),
            ("姓名標示（中） Attribution", lic.get("attribution_zh", "")),
            ("姓名標示（英） Attribution", lic.get("attribution_en", "")),
            ("開放政策 Policy", lic.get("policy_zh", "")),
            ("網站授權聲明 Site terms", lic.get("site_statement", ""))] if v]))
    img_fields = [("影像數量 Images", f"{len(m['pages'])} 幅"), ("取得方式 Source", m["images_note"])]
    if m.get("images_service"):
        img_fields.append(("服務位址 Service", m["images_service"] + "{影像編號}"))
    sections.append(Section("數位影像", "Digital images", fields=img_fields))
    extra = m.get("page_extra_label") or ""
    header = ["頁", "影像編號"] + ([extra] if extra else []) + ["像素"]
    rows = [[str(p["index"]), p["image_name"]] + ([p.get("extra") or ""] if extra else []) + [f"{p['width']}×{p['height']}"]
            for p in m["pages"]]
    sections.append(Section("影像清單", "Image list", header=header, rows=rows))
    prov = [(f"{a} {b}".strip(), v) for a, b, v, _ in m.get("provenance", [])]
    prov += [("擷取時間 Retrieved", m.get("retrieved", "")),
             ("附加檔案 Attachments", "、".join(Path(x[0]).name for x in m.get("attachments", []))),
             ("製作工具 Tools", f"bookget-py  {TOOL_URL}")]
    sections.append(Section("來源與製作", "Provenance", fields=prov))
    holder = m["holder"]
    head = f"{holder.get('zh') or 'bookget'}　{m['form_title']}"
    sub = " · ".join(x for x in [holder.get("en", ""), m.get("record_label", "")] if x)
    return SheetSpec(head, sub, sections)


def _build_native(m: Dict, book_dir: Path, out_path: Path, dpi: float, sheet: bool, sheet_dpi: int,
                  font_path: Optional[str]) -> Path:
    lic, holder = m["license"], m["holder"]
    creators = [c.strip() for c in (m.get("author") or "").replace("，", "；").split("；") if c.strip()]
    w = PdfWriter(dpi=dpi)
    w.info = {"Title": m["title"], "Author": m.get("author", ""), "Subject": m.get("subject", ""),
              "Keywords": ", ".join(m.get("keywords", [])), "Creator": f"bookget-py ({TOOL_URL})"}
    w.info.update({k: str(v) for k, v in m.get("pdfinfo", {}).items() if v})
    w.info.setdefault("Retrieved", m.get("retrieved", ""))
    w.xmp = {"title": m["title"], "creators": creators, "keywords": m.get("keywords", []), "description": m.get("subject", ""),
             "rights": lic.get("attribution_zh", ""), "license_url": lic.get("image_license_url", ""),
             "publisher": holder.get("zh", ""), "source": next((u for u in m.get("urls", {}).values() if u), ""),
             "identifier": m.get("pdfinfo", {}).get("ObjectNumber") or m.get("pdfinfo", {}).get("ObjectNumberPrefix") or "",
             "creator_tool": f"bookget-py ({TOOL_URL})"}
    for p in m["pages"]:
        idx = w.add_jpeg(_as_jpeg(book_dir / p["file"]), label=p["label"], dpi=dpi)
        for level, text in p.get("bookmarks", []):
            w.outlines.append(Outline(level, text, idx))
    if sheet:
        fp = font_path or find_cjk_font()
        if not fp:
            logger.warning("No CJK font found; metadata sheet skipped (set BOOKGET_CJK_FONT)")
        else:
            try:
                pages = render_sheet(sheet_spec(m), font_path=fp, dpi=sheet_dpi)
            except ImportError:
                logger.warning("Pillow not installed; metadata sheet skipped (pip install bookget[pdf])")
                pages = []
            if pages:
                first = w.page_count
                for pg in pages:
                    w.add_jpeg(pg, label=None, dpi=sheet_dpi)
                w.outlines.append(Outline(0, f"{m['form_title']} Metadata", first))
    for name, desc, mime in m.get("attachments", []):
        p = book_dir / name
        if p.exists():
            w.attachments.append(Attachment(Path(name).name, p.read_bytes(), mime, desc))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w.write(out_path)
    return out_path


def build_book_pdf(book_dir, out_path=None, *, engine: str = "native", sheet: bool = True, reverse: bool = False,
                   dpi: float = 300.0, name_prefix: Optional[str] = None, sheet_dpi: int = 200,
                   font_path: Optional[str] = None, verify: bool = True, keep_build: bool = False) -> Path:
    """Build the PDF for one downloaded book directory; returns the output path.

    ``engine`` is ``native`` (default) or ``latex``. ``name_prefix`` defaults to
    ``NPM`` for npm_taipei books and the upper-cased site id otherwise. With
    ``verify`` (and PyMuPDF installed) the result is checked for byte-identical
    images and blank pages; a failure raises RuntimeError.
    """
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}; choose from {ENGINES}")
    book_dir = Path(book_dir)
    m = document_schema(book_dir, dpi=dpi, reverse=reverse, name_prefix=name_prefix)
    out_path = Path(out_path) if out_path else book_dir / "pdf" / (m["file_stem"] + ".pdf")
    if engine == "latex":
        from .latex import build_latex_pdf
        if not sheet:
            logger.info("--no-sheet is ignored by the latex engine (the form is part of the document)")
        build_latex_pdf(m, book_dir, out_path, dpi=dpi, keep_build=keep_build)
    else:
        _build_native(m, book_dir, out_path, dpi, sheet, sheet_dpi, font_path)
    if verify:
        res = verify_pdf(out_path, [book_dir / p["file"] for p in m["pages"]])
        if res is None:
            logger.warning("PyMuPDF not installed; skipping verification (pip install bookget[pdf])")
        elif not res[0]:
            raise RuntimeError(f"verification failed for {out_path.name}: {res[1]}")
        else:
            logger.info(f"verified: {res[2]} pages, {res[3]} image pages, images byte-identical")
    logger.info(f"PDF written: {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return out_path


def build_many(dirs: Sequence[Path], **kw) -> List[Path]:
    out = []
    for d in dirs:
        try:
            out.append(build_book_pdf(d, **kw))
        except Exception as e:
            logger.error(f"{d}: {e}")
    return out


__all__ = ["build_book_pdf", "build_many", "pdf_filename", "sheet_spec", "list_images", "ENGINES"]
