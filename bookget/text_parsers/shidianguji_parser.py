# ShidianGuji (识典古籍) text parser
#
# API paragraph format (contentEncryptType: 0, unencrypted):
#   content:          JSON string → {"lines": [{"lineType": int, "content": str}, ...]}
#   translateContent: JSON string → {"sentences": [{"content": str}, ...]}
#
# lineType values observed: 1 = body text, others may be headings / annotations

import json
from typing import List, Optional
from .base import StructuredText, BaseTextParser


class ShidianGujiParser(BaseTextParser):
    """
    Parser for 识典古籍 paragraph API responses.

    Converts the paragraphs list from book/paragraphs/v2 into StructuredText.
    Paragraphs are grouped by chapterId / chapterOrder to reconstruct chapters.
    """

    site_id = "shidianguji"

    def parse(
        self,
        paragraphs: List[dict],
        book_id: str,
        url: str,
        metadata: Optional[dict] = None,
    ) -> StructuredText:
        """
        Parse paragraphs list into StructuredText.

        Args:
            paragraphs: List of paragraph dicts from paragraphs/v2 API.
            book_id:    Book identifier.
            url:        Original book URL.
            metadata:   Optional dict with title, authors_json, dynasty, catalog.
        """
        meta = metadata or {}
        title = meta.get("title", "")

        # Build chapter title lookup from catalog
        catalog = meta.get("catalog", [])
        catalog_title: dict[str, str] = {}
        if isinstance(catalog, list):
            for item in catalog:
                cid = str(item.get("chapterId") or item.get("id", ""))
                ctitle = item.get("title") or item.get("name") or ""
                if cid:
                    catalog_title[cid] = ctitle

        # Group paragraphs by chapter, preserving order
        chapter_order: list[str] = []        # chapter_id list in encounter order
        chapter_paras: dict[str, list] = {}  # chapter_id → [paragraph dict, ...]

        for para in paragraphs:
            cid = str(para.get("chapterId", ""))
            if cid not in chapter_paras:
                chapter_order.append(cid)
                chapter_paras[cid] = []
            chapter_paras[cid].append(para)

        # Convert each chapter's paragraphs into text strings
        chapters = []
        for ch_idx, cid in enumerate(chapter_order):
            paras = chapter_paras[cid]
            # Use chapterOrder from first para for sorting if needed
            ch_order = paras[0].get("chapterOrder", ch_idx + 1) if paras else ch_idx + 1
            ch_title = catalog_title.get(cid, f"第{ch_idx + 1}章")

            text_lines: list[str] = []
            for para in sorted(paras, key=lambda p: p.get("inChapterOrder", 0)):
                text = _extract_paragraph_text(para)
                if text:
                    text_lines.append(text)

            if not text_lines:
                continue

            chapters.append({
                "id": cid,
                "title": ch_title,
                "order": ch_order,
                "paragraphs": text_lines,
            })

        # Sort chapters by chapterOrder
        chapters.sort(key=lambda c: c["order"])

        if not chapters:
            return StructuredText(source=self._make_source(book_id, url))

        content_type = "book_with_chapters" if len(chapters) > 1 else "single_chapter"

        # Build metadata block
        meta_dict: dict = {}
        authors_json = meta.get("authors_json", "[]")
        try:
            authors = json.loads(authors_json) if isinstance(authors_json, str) else authors_json
            if authors:
                meta_dict["authors"] = [
                    {"name": a.get("name", ""), "role": a.get("role", "")}
                    for a in authors if a.get("name")
                ]
        except (json.JSONDecodeError, TypeError):
            pass
        if meta.get("dynasty"):
            meta_dict["dynasty"] = meta["dynasty"]

        return StructuredText(
            source=self._make_source(book_id, url),
            title=title,
            content_type=content_type,
            metadata=meta_dict,
            chapters=chapters,
        )


def _extract_paragraph_text(para: dict) -> str:
    """Extract plain text from a paragraph dict.

    Combines lines from the 'content' JSON field.
    Returns empty string if content is absent or unparseable.
    """
    content_raw = para.get("content", "")
    if not content_raw:
        return ""
    try:
        content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        lines = content.get("lines", [])
        # Concatenate all line contents (ignore lineType for plain text output)
        texts = [line.get("content", "").strip() for line in lines if line.get("content")]
        return "".join(texts)
    except (json.JSONDecodeError, TypeError, AttributeError):
        # Fallback: treat as plain string
        return str(content_raw).strip()
