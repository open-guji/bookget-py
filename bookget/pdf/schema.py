"""Document schema for the PDF builders.

Both engines (the pure-Python writer and LuaLaTeX) render the same document
description, built here from a downloaded book directory::

    {
      "title", "file_stem", "form_title", "record_label", "title_field",
      "author", "subject", "keywords": [...],
      "pdfinfo": {Key: value},                      custom Info-dictionary keys
      "holder": {"zh", "en", "url"},
      "urls": {name: url},
      "license": {"image_license", "image_license_url", "image_tier",
                  "attribution_zh", "attribution_en", "policy_zh", "site_statement"},
      "sections": [ {"id", "title_zh", "title_en", "note",
                     "fields": [{"label_zh", "label_en", "value"}]          # form
                     | "header_zh": [...], "header_en": [...] | None,
                       "rows": [[...]], "widths": [...] | None } ],           # table
      "pages": [ {"index", "image_name", "extra", "label", "width", "height",
                  "file", "bookmarks": [[level, text]], "record_id"} ],
      "provenance": [[label_zh, label_en, value, is_url]],
      "images_note", "images_service", "page_extra_label",
      "attachments": [[path, description, mime]],
      "retrieved", "dpi"
    }

Three sources are recognised: an NPM work (album mode; raw record has
``kind: work``), a single NPM record (``kind: record``) and any other bookget
download (generic form from metadata.json).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from .writer import jpeg_size

logger = logging.getLogger(__name__)

SITE = "https://digitalarchive.npm.gov.tw"
IIIF_IMAGE = "https://iiifod.npm.gov.tw/iiif/2"
TOOL_URL = "https://github.com/open-guji/bookget-py"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")

NPM_HOLDER = {"zh": "國立故宮博物院", "en": "National Palace Museum, Taipei", "url": "https://www.npm.gov.tw"}
NPM_POLICY = ("開放院藏書畫類、器物類、織品類文物中階圖像（600萬畫素），中階圖檔及本網站文字均以「CC授權條款4.0」之"
              "CC BY 姓名標示規範，無須申請、不限用途、不用付費即可公開使用，惟需於適當位置呈現中文或英文姓名標示。")
NPM_FIELD_EN = {"文物統一編號": "Object Number", "作品號": "Work number", "品名": "Title", "分類": "Category",
                "作者": "Author", "書體": "Script", "數量": "Quantity", "作品語文": "Language",
                "釋文": "Transcription", "創作時間": "Date", "文物統一編號（其他）": "Other object numbers"}
LICENSE_URLS = {
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "PDM": "https://creativecommons.org/publicdomain/mark/1.0/",
}


def zh_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").replace("　", " ")).strip()
    return re.sub(r"\s[\[(]?[A-Z][A-Za-z].*$", "", t).strip()


def file_stem(md: Dict, prefix: str = "") -> str:
    """Commons-friendly stem: ``<prefix>-<number>_<title>``.

    The album-level suffix ``N000000000`` is dropped; a leaf's ``N000000012``
    is kept so leaf and album files differ. Whitespace, slashes and brackets
    become underscores."""
    title = zh_title(md.get("title", "")) or md.get("source_id", "book")
    num = re.sub(r"N0{9}$", "", (md.get("call_number") or "").strip())
    stem = f"{num}_{title}" if num else f"{md.get('source_id') or 'book'}_{title}"
    if prefix:
        stem = f"{prefix}-{stem}"
    return re.sub(r"[\s/\\:*?\"<>|（）()\[\]]+", "_", stem).strip("_")[:180]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def list_images(book_dir: Path) -> List[Path]:
    img_dir = book_dir / "images"
    if not img_dir.is_dir():
        raise FileNotFoundError(f"no images/ directory in {book_dir}")
    files = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS and p.is_file())
    if not files:
        raise FileNotFoundError(f"no image files in {img_dir}")
    return files


def _image_size(path: Path):
    data = path.read_bytes()
    try:
        w, h, _ = jpeg_size(data)
        return w, h
    except ValueError:
        from PIL import Image          # non-JPEG pages: Pillow (optional dependency)
        with Image.open(path) as im:
            return im.size


def _page_label(path: Path) -> str:
    m = re.match(r"^\d{3,4}_(.+)$", path.stem)
    return m.group(1) if m else path.stem


def _pages(images: List[Path]) -> List[Dict]:
    pages = []
    for i, p in enumerate(images, 1):
        w, h = _image_size(p)
        name = _page_label(p)
        pages.append({"index": i, "image_name": name, "extra": "", "label": name, "width": w, "height": h,
                      "file": f"images/{p.name}", "bookmarks": [[0, f"第 {i} 幅  {name}"]], "record_id": ""})
    return pages


def _attachments(book_dir: Path, site: str) -> List[List[str]]:
    out = [["metadata.json", "bookget metadata (BookMetadata)", "application/json"]]
    if site and (book_dir / f"raw.{site}.json").exists():
        out.append([f"raw.{site}.json", "Source record(s) as parsed from the site", "application/json"])
    return out


# ---------------------------------------------------------------- NPM: single record
def npm_record_schema(md: Dict, raw: Dict, pages: List[Dict], book_dir: Path, dpi: float) -> Dict:
    fields = raw.get("fields", {})
    sec, sec_en = raw.get("sections", {}), raw.get("sections_en", {})
    title = md.get("title") or fields.get("品名", "")
    num = fields.get("文物統一編號", "")
    oid = md.get("source_id", "")
    seals = [r[2] for r in sec.get("details-5", {}).get("rows", []) if len(r) >= 3]
    dims = "；".join(f"{r[0]} {r[1]}" for r in sec.get("details-2", {}).get("rows", []) if len(r) >= 2)
    attribution = raw.get("attribution") or f"{title}。國立故宮博物院，台北，CC BY 4.0 @ www.npm.gov.tw"
    attribution_en = f"{zh_title(title)}, The National Palace Museum, Taipei, CC BY 4.0 @ www.npm.gov.tw"

    sections = []
    for pid, s in sec.items():
        e = sec_en.get(pid, {})
        entry = {"id": pid, "title_zh": s.get("title", pid), "title_en": e.get("title") or "", "note": s.get("note")}
        if s.get("header"):
            entry.update(header_zh=s["header"], header_en=e.get("header"), rows=s.get("rows", []), widths=None)
        else:
            en_rows = e.get("rows", [])
            entry["fields"] = [{"label_zh": r[0], "label_en": (en_rows[i][0] if i < len(en_rows) and en_rows[i] else NPM_FIELD_EN.get(r[0])),
                                "value": r[1]} for i, r in enumerate(s.get("rows", [])) if len(r) >= 2]
            if pid == "details-1" and fields.get("文物統一編號（其他）"):
                entry["fields"].append({"label_zh": "文物統一編號（其他）", "label_en": "Other object numbers",
                                        "value": fields["文物統一編號（其他）"]})
        if entry.get("fields") or entry.get("rows") or entry.get("note"):
            sections.append(entry)

    urls = {"detail_zh": raw.get("detail_url", ""), "detail_en": raw.get("detail_url_en", ""),
            "iiif_viewer": raw.get("viewer_url", ""), "iiif_manifest": raw.get("manifest_url", "")}
    p0 = pages[0] if pages else {"width": 0, "height": 0, "image_name": ""}
    return {
        "source_system": "npm-opendata", "title": title, "file_stem": file_stem(md, "NPM"),
        "form_title": "文物資料表", "record_label": f"Object Record · Open Data {oid}", "title_field": "品名",
        "author": fields.get("作者", ""),
        "subject": f'{fields.get("分類", "")}，{fields.get("作者", "")}，{fields.get("書體", "")}，{fields.get("數量", "")}。'
                   f'尺寸(公分)：{dims}。{NPM_HOLDER["zh"]}典藏，文物統一編號 {num}。',
        "keywords": [k for k in [fields.get("作者"), fields.get("分類"), fields.get("書體"), md.get("category"),
                                 NPM_HOLDER["zh"], NPM_HOLDER["en"], "IIIF", "Open Data", "CC BY 4.0"] + seals if k],
        "pdfinfo": {"ObjectNumber": num, "WorkNumber": fields.get("作品號"), "Category": fields.get("分類"),
                    "Script": fields.get("書體"), "Quantity": fields.get("數量"), "WorkLanguage": fields.get("作品語文"),
                    "Transcription": fields.get("釋文"), "Holder": f'{NPM_HOLDER["zh"]} / {NPM_HOLDER["en"]}',
                    "License": "CC BY 4.0", "Attribution": attribution, "AttributionEN": attribution_en,
                    "IIIFManifest": urls["iiif_manifest"], "IIIFViewer": urls["iiif_viewer"],
                    "SourceDetailZH": urls["detail_zh"], "SourceDetailEN": urls["detail_en"], "OpenDataID": oid,
                    "ImageIDs": ", ".join(p["image_name"] for p in pages),
                    "ImagePixels": f'{p0["width"]}x{p0["height"]} (IIIF full/full, JPEG embedded unmodified)'},
        "holder": dict(NPM_HOLDER), "urls": urls,
        "license": {"image_license": "CC BY 4.0", "image_license_url": LICENSE_URLS["CC BY 4.0"],
                    "image_tier": "600萬像素圖檔（中階圖像）/ IIIF full resolution",
                    "attribution_zh": attribution, "attribution_en": attribution_en,
                    "policy_zh": NPM_POLICY, "site_statement": "https://data.gov.tw/license"},
        "sections": sections, "pages": pages,
        "provenance": [["典藏單位", "Holder", f'{NPM_HOLDER["zh"]} / {NPM_HOLDER["en"]}', False],
                       ["詳細資料（中）", "Detail page", urls["detail_zh"], True],
                       ["詳細資料（英）", "Detail page", urls["detail_en"], True],
                       ["IIIF Viewer", "", urls["iiif_viewer"], True], ["IIIF Manifest", "", urls["iiif_manifest"], True]],
        "images_note": f"IIIF Image API 2 full/full/0/default.jpg（原始最高解析度），JPEG 資料原樣嵌入本 PDF，未重新編碼；頁面尺寸以 {dpi:g} dpi 換算",
        "images_service": f"{IIIF_IMAGE}/{p0['image_name'][:3]}%2F" if p0["image_name"] else IIIF_IMAGE + "/",
        "page_extra_label": "Open Data",
        "attachments": _attachments(book_dir, md.get("source_site", "")), "retrieved": _now(), "dpi": dpi,
    }


# ---------------------------------------------------------------- NPM: work (album mode)
def npm_work_schema(md: Dict, raw: Dict, pages: List[Dict], book_dir: Path, dpi: float) -> Dict:
    records = raw.get("records", [])
    # image N-part -> owning record: a record's own number first, then numbers it
    # lists as "other" (a leaf spanning two images carries both)
    by_leaf = {}
    for r in sorted(records, key=lambda r: int(r["id"])):
        if r.get("object_number"):
            by_leaf.setdefault(r["object_number"][-10:], r)
    for r in sorted(records, key=lambda r: int(r["id"])):
        for n in r.get("object_numbers_more", []):
            by_leaf.setdefault(n[-10:], r)
    key, prefix = raw.get("key", ""), raw.get("prefix", "")
    album = min([r for r in records if r["object_number"].endswith("N000000000")] or records,
                key=lambda r: (len(zh_title(r["title"])), int(r["id"]))) if records else {"fields": {}, "sections": {}, "id": "", "title": ""}
    af = album["fields"]
    wtitle = md.get("title") or zh_title(album["title"])
    dep = (records[0].get("dep") if records else "P") or "P"

    # per-page: the leaf record owning the image, a bookmark on the first image of each leaf
    leaf_seen = set()
    for p in pages:
        lab = p["image_name"]
        r = by_leaf.get(lab[9:19]) or album
        p["extra"] = r.get("object_number") or (f"{dep}{r['id']}" if r.get("id") else "")
        p["record_id"] = r.get("id", "")
        leaf = lab[:19]
        p["bookmarks"] = []
        if leaf not in leaf_seen:
            leaf_seen.add(leaf)
            p["bookmarks"].append([0, f"{r.get('object_number') or leaf}  {zh_title(r.get('title', ''))}".strip()])

    basic = [{"label_zh": "作品", "label_en": "Work", "value": wtitle},
             {"label_zh": "統一編號前綴", "label_en": "Object number prefix", "value": prefix},
             {"label_zh": "記錄數 / 影像數", "label_en": "Records / images", "value": f"{len(records)} 筆 / {len(pages)} 幅"}]
    for s in album["sections"].values():
        if not s.get("header"):
            for r in s.get("rows", []):
                if len(r) >= 2 and r[0] != "釋文":
                    basic.append({"label_zh": r[0], "label_en": NPM_FIELD_EN.get(r[0]), "value": r[1]})
    sections = [{"id": "basic", "title_zh": "基本資料（總記錄）", "title_en": "Details of the album record", "note": None, "fields": basic}]
    for pid, s in album["sections"].items():
        if s.get("header") and s.get("rows"):
            sections.append({"id": pid, "title_zh": s["title"] + "（總記錄）", "title_en": "", "note": None,
                             "header_zh": s["header"], "header_en": None, "rows": s["rows"], "widths": None})
    ordered = sorted(records, key=lambda r: (r["object_number"], int(r["id"])))
    sections.append({"id": "leaves", "title_zh": "開頁記錄", "title_en": "Leaf records", "note": None,
                     "header_zh": ["序", "文物統一編號", "品名", "Open Data"], "header_en": None,
                     "rows": [[str(n), r["object_number"] or "", zh_title(r["title"]), f"{dep}{r['id']}"] for n, r in enumerate(ordered, 1)],
                     "widths": ["8mm", "50mm", None, "18mm"]})
    trans = [[r["object_number"], r["fields"]["釋文"]] for r in ordered if r["fields"].get("釋文")]
    if trans:
        sections.append({"id": "trans", "title_zh": "釋文（各記錄）", "title_en": "Transcriptions", "note": None,
                         "header_zh": ["文物統一編號", "釋文"], "header_en": None, "rows": trans, "widths": ["50mm", None]})
    for pid, ttl, widths in [("details-5", "印記資料（各記錄）", ["50mm", "24mm", "30mm", None]),
                             ("details-4", "題跋資料（各記錄）", ["34mm", "16mm", "18mm", "14mm", "22mm", "12mm", None]),
                             ("details-2", "典藏尺寸（各記錄）", ["50mm", None, None]),
                             ("details-3", "質地（各記錄）", ["50mm", None, None])]:
        rows = [[r["object_number"]] + row for r in ordered if r is not album
                for row in r["sections"].get(pid, {}).get("rows", [])]
        if rows:
            hdr = next((r["sections"][pid]["header"] for r in ordered if r["sections"].get(pid, {}).get("header")), [])
            sections.append({"id": pid + "-all", "title_zh": ttl, "title_en": "", "note": None,
                             "header_zh": ["文物統一編號"] + hdr, "header_en": None, "rows": rows, "widths": widths})

    leaf_authors, seen = [], set()
    for r in ordered:
        for x in re.split(r"[、;；]", r["fields"].get("作者", "")):
            x = x.strip()
            z = x.split(",")[0].strip()
            if z and z not in seen:
                seen.add(z)
                leaf_authors.append(x)
    author = af.get("作者", "") or "；".join(leaf_authors[:12])
    album_url = raw.get("album_detail_url") or album.get("detail_url", "")
    manifest_url = raw.get("album_manifest_url", "")
    attribution = f"{wtitle}。國立故宮博物院，台北，CC BY 4.0 @ www.npm.gov.tw"
    return {
        "source_system": "npm-opendata-work", "category": md.get("category", ""), "object_id": key,
        "title": wtitle, "file_stem": file_stem(md, "NPM"),
        "form_title": "文物資料表", "record_label": f"Open Data 書畫類 · {prefix} · {len(records)} 筆記錄",
        "title_field": "作品", "author": author,
        "subject": "，".join(x for x in [af.get("分類", ""), author.replace("；", "、"), af.get("書體", "")] if x)
                   + f"。{prefix}，{len(records)} 筆記錄，{len(pages)} 幅影像。國立故宮博物院典藏。",
        "keywords": [k for k in [wtitle, author, af.get("分類"), af.get("書體"), md.get("category"), NPM_HOLDER["zh"],
                                 NPM_HOLDER["en"], "IIIF", "Open Data", "CC BY 4.0"] if k],
        "pdfinfo": {"ObjectNumberPrefix": prefix, "Calligraphers": "；".join(leaf_authors),
                    "ObjectNumbers": ", ".join(r["object_number"] for r in ordered if r["object_number"]),
                    "OpenDataIDs": ", ".join(f"{dep}{r['id']}" for r in ordered), "Category": af.get("分類"),
                    "Script": af.get("書體"), "Holder": f'{NPM_HOLDER["zh"]} / {NPM_HOLDER["en"]}', "License": "CC BY 4.0",
                    "Attribution": attribution, "AlbumRecordURL": album_url,
                    "ImageIDs": ", ".join(p["image_name"] for p in pages),
                    "ImagePixels": "IIIF full/full, JPEG embedded unmodified"},
        "holder": dict(NPM_HOLDER), "urls": {"album_detail": album_url, "album_manifest": manifest_url},
        "provenance": [["典藏單位", "Holder", f'{NPM_HOLDER["zh"]} / {NPM_HOLDER["en"]}', False],
                       ["總記錄詳細資料", "Album record", album_url, True],
                       ["總記錄 IIIF manifest", "", manifest_url, True],
                       ["各開記錄", "Leaf records", "見「開頁記錄」表之 Open Data 編號，網址格式 " + SITE + "/opendata/Pub/Detail?id=<編號>&dep=" + dep, False]],
        "license": {"image_license": "CC BY 4.0", "image_license_url": LICENSE_URLS["CC BY 4.0"],
                    "image_tier": "600萬像素圖檔（中階圖像）/ IIIF full resolution",
                    "attribution_zh": attribution,
                    "attribution_en": f"{wtitle}, The National Palace Museum, Taipei, CC BY 4.0 @ www.npm.gov.tw",
                    "policy_zh": NPM_POLICY, "site_statement": "https://data.gov.tw/license"},
        "images_note": f"IIIF Image API 2 full/full/0/default.jpg（原始最高解析度），JPEG 資料原樣嵌入本 PDF，未重新編碼；"
                       f"頁面尺寸以 {dpi:g} dpi 換算；影像依影像編號排序（記錄 N 號、影像 P 序）",
        "images_service": f"{IIIF_IMAGE}/{key[:3]}%2F" if key else IIIF_IMAGE + "/", "dpi": dpi,
        "page_extra_label": "文物統一編號", "sections": sections, "pages": pages,
        "attachments": _attachments(book_dir, md.get("source_site", "")), "retrieved": _now(),
    }


# ---------------------------------------------------------------- generic
def generic_schema(md: Dict, raw: Optional[Dict], pages: List[Dict], book_dir: Path, dpi: float, prefix: str) -> Dict:
    creators = "；".join(c.get("name", "") + (f"（{c['role']}）" if c.get("role") else "") for c in md.get("creators", []))
    basic = [("品名", "Title", md.get("title", "")), ("作者", "Creator", creators), ("朝代", "Dynasty", md.get("dynasty", "")),
             ("創作時間", "Date", md.get("date", "")), ("出版者", "Publisher", md.get("publisher", "")),
             ("分類", "Category", md.get("category", "")), ("類型", "Type", md.get("doc_type", "")),
             ("數量", "Quantity", md.get("volume_info", "")), ("尺寸", "Dimensions", md.get("dimensions", "")),
             ("索書號／編號", "Call number", md.get("call_number", "")), ("典藏單位", "Repository", md.get("collection_unit", "")),
             ("來源", "Source", md.get("source_url", "")), ("IIIF", "IIIF manifest", md.get("iiif_manifest_url", ""))]
    sections = [{"id": "basic", "title_zh": "基本資料", "title_en": "Record", "note": None,
                 "fields": [{"label_zh": a, "label_en": b, "value": v} for a, b, v in basic if v]}]
    if md.get("notes"):
        sections.append({"id": "notes", "title_zh": "附註", "title_en": "Notes", "note": None,
                         "fields": [{"label_zh": "", "label_en": "", "value": n} for n in md["notes"]]})
    if md.get("provenance"):
        sections.append({"id": "prov", "title_zh": "題跋／印記", "title_en": "Provenance", "note": None,
                         "fields": [{"label_zh": "", "label_en": "", "value": n} for n in md["provenance"]]})
    holder = {"zh": md.get("collection_unit", ""), "en": "", "url": ""}
    lic = md.get("license", "")
    return {
        "source_system": md.get("source_site", ""), "title": md.get("title", "") or book_dir.name,
        "file_stem": file_stem(md, prefix), "form_title": "文獻資料表",
        "record_label": f"{md.get('source_site', '')} · {md.get('source_id', '')}".strip(" ·"), "title_field": "品名",
        "author": creators, "subject": "；".join(x for x in [md.get("collection_unit"), md.get("category")] if x),
        "keywords": [k for k in [md.get("collection_unit"), md.get("category"), md.get("dynasty"), md.get("call_number")] if k],
        "pdfinfo": {"SourceURL": md.get("source_url"), "SourceSite": md.get("source_site"), "SourceId": md.get("source_id"),
                    "CallNumber": md.get("call_number"), "License": lic, "Attribution": md.get("rights")},
        "holder": holder, "urls": {"source": md.get("source_url", "")},
        "license": {"image_license": lic, "image_license_url": LICENSE_URLS.get(lic, ""), "image_tier": "",
                    "attribution_zh": md.get("rights", ""), "attribution_en": "", "policy_zh": "", "site_statement": ""},
        "sections": sections, "pages": pages,
        "provenance": [["來源", "Source", md.get("source_url", ""), True]] if md.get("source_url") else [],
        "images_note": f"頁面影像原樣嵌入本 PDF；頁面尺寸以 {dpi:g} dpi 換算", "images_service": "",
        "page_extra_label": "", "attachments": _attachments(book_dir, md.get("source_site", "")),
        "retrieved": _now(), "dpi": dpi,
    }


def load_json(path: Path) -> Optional[Dict]:
    if path.exists() and path.stat().st_size:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            logger.warning(f"Ignoring unreadable JSON: {path}")
    return None


def document_schema(book_dir, dpi: float = 300.0, reverse: bool = False, name_prefix: Optional[str] = None) -> Dict:
    """Build the schema for a downloaded book directory (images/ + metadata.json [+ raw.<site>.json])."""
    book_dir = Path(book_dir)
    md = load_json(book_dir / "metadata.json") or {}
    site = md.get("source_site", "")
    raw = load_json(book_dir / f"raw.{site}.json") if site else None
    images = list_images(book_dir)
    if reverse:
        images = images[::-1]
    pages = _pages(images)
    if name_prefix is None:
        name_prefix = "NPM" if site == "npm_taipei" else (site.upper() if site else "")
    if site == "npm_taipei" and raw and raw.get("kind") == "work":
        schema = npm_work_schema(md, raw, pages, book_dir, dpi)
    elif site == "npm_taipei" and raw and raw.get("fields") is not None:
        schema = npm_record_schema(md, raw, pages, book_dir, dpi)
    else:
        schema = generic_schema(md, raw, pages, book_dir, dpi, name_prefix)
    if name_prefix != ("NPM" if site == "npm_taipei" else (site.upper() if site else "")):
        schema["file_stem"] = file_stem(md, name_prefix)
    return schema
