# Hanchi (漢籍全文資料庫) text parser
# Converts chapter data fetched from the Hanchi CGI into StructuredText.
# Each chapter comes from a friendly-print (action 810) page.

import html
import re

from .base import BaseTextParser, StructuredText


class HanchiParser(BaseTextParser):
    """Parser for Hanchi (hanchi.ihp.sinica.edu.tw) text content."""

    site_id = "hanchi"

    def parse_book(
        self,
        chapter_data: list[dict],
        book_metadata: dict,
        book_id: str,
        url: str,
        index_id: str = "",
    ) -> StructuredText:
        """Parse multi-chapter book into StructuredText.

        Args:
            chapter_data: List of dicts with keys:
                - node_id: str
                - title: str
                - breadcrumb: str
                - paragraphs: list[str]
            book_metadata: Dict with keys: title, category, publisher, place, date, notes
            book_id: Composite book ID (e.g. "hanjishilu:30211001")
            url: Source URL
            index_id: Global index ID
        """
        chapters = []
        for i, ch in enumerate(chapter_data):
            paragraphs = self._clean_paragraphs(ch.get("paragraphs", []))
            if not paragraphs:
                continue

            chapters.append({
                "id": ch.get("node_id", str(i + 1)),
                "title": ch.get("title", f"Chapter {i + 1}"),
                "order": i + 1,
                "breadcrumb": ch.get("breadcrumb", ""),
                "paragraphs": paragraphs,
            })

        content_type = "book_with_chapters" if len(chapters) > 1 else "single_chapter"

        return StructuredText(
            source=self._make_source(book_id, url, index_id=index_id),
            title=book_metadata.get("title", ""),
            content_type=content_type,
            metadata=self._build_metadata(book_metadata),
            chapters=chapters,
        )

    async def parse(self, raw_data: dict, book_id: str, url: str, index_id: str = "") -> StructuredText:
        """Standard parse method (interface compliance)."""
        return self.parse_book(
            raw_data.get("chapters", []),
            raw_data.get("metadata", {}),
            book_id,
            url,
            index_id=index_id,
        )

    def _clean_paragraphs(self, paragraphs: list[str]) -> list[str]:
        """Clean paragraph text.

        Strips HTML entities, removes page-number-only lines and empty paragraphs.
        """
        result = []
        for p in paragraphs:
            text = html.unescape(p).strip()
            if not text:
                continue
            # Skip decorative separators like "．　．　．　．"
            if re.match(r'^[．\.\s　]+$', text):
                continue
            result.append(text)
        return result

    def _build_metadata(self, book_metadata: dict) -> dict:
        """Build structured metadata dict."""
        meta = {}
        for key in ("category", "publisher", "place", "date", "notes"):
            if book_metadata.get(key):
                meta[key] = book_metadata[key]
        meta["collection"] = "中央研究院歷史語言研究所漢籍電子文獻"
        return meta
