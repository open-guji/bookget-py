"""CText text parser — converts CText API/HTML data to StructuredText.

Handles three CText content types:
1. Classic/path texts (single chapter from API fulltext)
2. Wiki book (multi-chapter, each chapter from API)
3. Wiki chapter (single chapter from API)
"""

import re

from .base import BaseTextParser, StructuredText

# Standalone lines that should be promoted to level-2 headers (**prefix)
_HEADING_PROMOTIONS = re.compile(r"^(附錄)$")


class CTextParser(BaseTextParser):
    """Parser for CText (ctext.org) text content."""

    site_id = "ctext"

    @staticmethod
    def _normalize_paragraphs(paragraphs: list[str]) -> list[str]:
        """Normalize paragraphs: promote standalone heading lines to ** markers.

        CText wiki data sometimes has headings like "附錄" as plain text lines
        without any * prefix. This promotes them to level-2 headers (**附錄)
        so downstream parsers can recognize them as category boundaries.
        """
        result = []
        for p in paragraphs:
            stripped = p.strip()
            if _HEADING_PROMOTIONS.match(stripped):
                result.append(f"**{stripped}")
            else:
                result.append(p)
        return result

    async def parse(self, raw_data: dict, book_id: str, url: str, index_id: str = "") -> StructuredText:
        """Standard parse method (not used directly by CTextAdapter but for interface)."""
        return self.parse_classic(raw_data, book_id, url, index_id=index_id)

    def parse_classic(
        self,
        api_response: dict,
        book_id: str,
        url: str,
        index_id: str = "",
    ) -> StructuredText:
        """Parse a classic/path text or single wiki chapter.

        Args:
            api_response: CText API response dict with 'title' and 'fulltext'
            book_id: e.g. "path:analects/xue-er" or "wiki-chapter:12345"
            url: Original URL
            index_id: Global index ID
        """
        title = api_response.get("title", "")
        fulltext = api_response.get("fulltext", [])
        if isinstance(fulltext, str):
            fulltext = [fulltext]

        paragraphs = self._normalize_paragraphs(
            [str(p) for p in fulltext if p]
        )

        return StructuredText(
            source=self._make_source(book_id, url, index_id=index_id),
            title=title,
            content_type="single_chapter",
            metadata=self._extract_metadata(api_response),
            chapters=[
                {
                    "id": book_id,
                    "title": title,
                    "order": 1,
                    "paragraphs": paragraphs,
                }
            ],
        )

    def parse_wiki_book(
        self,
        chapter_data: list[tuple[str, dict]],
        book_metadata: dict,
        book_id: str,
        url: str,
        index_id: str = "",
    ) -> StructuredText:
        """Parse a multi-chapter wiki book.

        Args:
            chapter_data: List of (chapter_id, api_response) tuples
            book_metadata: Book-level metadata dict (title, authors, dynasty, etc.)
            book_id: e.g. "wiki-book:1347940"
            url: Original URL
            index_id: Global index ID
        """
        chapters = []
        for i, (ch_id, resp) in enumerate(chapter_data):
            title = resp.get("title", f"Chapter {i + 1}")
            fulltext = resp.get("fulltext", [])
            if isinstance(fulltext, str):
                fulltext = [fulltext]

            paragraphs = self._normalize_paragraphs(
                [str(p) for p in fulltext if p]
            )

            chapters.append(
                {
                    "id": str(ch_id),
                    "title": title,
                    "order": i + 1,
                    "source_url": f"https://ctext.org/wiki.pl?if=gb&chapter={ch_id}",
                    "paragraphs": paragraphs,
                }
            )

        return StructuredText(
            source=self._make_source(book_id, url, index_id=index_id),
            title=book_metadata.get("title", ""),
            content_type="book_with_chapters",
            metadata=self._build_book_metadata(book_metadata),
            chapters=chapters,
        )

    def parse_html_text(
        self,
        text_parts: list[str],
        title: str,
        book_id: str,
        url: str,
        index_id: str = "",
    ) -> StructuredText:
        """Parse text extracted from HTML (fallback when API is unavailable).

        Args:
            text_parts: List of text segments from HTML parsing
            title: Page title
            book_id: Book identifier
            url: Original URL
            index_id: Global index ID
        """
        return StructuredText(
            source=self._make_source(book_id, url, index_id=index_id),
            title=title,
            content_type="single_chapter",
            metadata={},
            chapters=[
                {
                    "id": book_id,
                    "title": title,
                    "order": 1,
                    "paragraphs": text_parts,
                }
            ],
        )

    def _extract_metadata(self, api_response: dict) -> dict:
        """Extract metadata fields from a CText API response."""
        meta = {}
        if api_response.get("author"):
            meta["authors"] = [
                {"name": api_response["author"], "role": "撰"}
            ]
        if api_response.get("dynasty"):
            meta["dynasty"] = api_response["dynasty"]
        if api_response.get("category"):
            meta["category"] = api_response["category"]
        urn = api_response.get("urn", "")
        if urn:
            meta["urn"] = urn
        return meta

    def _build_book_metadata(self, book_metadata: dict) -> dict:
        """Build structured metadata from book-level info."""
        meta = {}
        if book_metadata.get("authors"):
            meta["authors"] = book_metadata["authors"]
        elif book_metadata.get("author"):
            meta["authors"] = [
                {"name": book_metadata["author"], "role": "撰"}
            ]
        if book_metadata.get("dynasty"):
            meta["dynasty"] = book_metadata["dynasty"]
        if book_metadata.get("category"):
            meta["category"] = book_metadata["category"]
        if book_metadata.get("urn"):
            meta["urn"] = book_metadata["urn"]
        if book_metadata.get("volumes"):
            meta["volumes"] = book_metadata["volumes"]
        return meta
