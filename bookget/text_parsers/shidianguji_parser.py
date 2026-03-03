# ShidianGuji (识典古籍) text parser

from typing import List, Optional
from .base import StructuredText, BaseTextParser


class ShidianGujiParser(BaseTextParser):
    """
    Parser for 识典古籍 text content.

    Converts chapter_list API response to StructuredText.
    Each chapter has title and content fields.
    """

    site_id = "shidianguji"

    def parse(
        self,
        chapter_list: List[dict],
        book_id: str,
        url: str,
        metadata: Optional[dict] = None,
    ) -> StructuredText:
        """
        Parse chapter list into StructuredText.

        Args:
            chapter_list: List of chapter dicts with 'title' and 'content' keys.
            book_id: Book identifier.
            url: Original URL.
            metadata: Optional book metadata dict (title, author, dynasty, etc.)
        """
        chapters = []
        for i, ch in enumerate(chapter_list):
            content = ch.get("content", "")
            if not content:
                continue

            # Split content into paragraphs by newlines
            paragraphs = [p.strip() for p in content.split("\n") if p.strip()]

            chapters.append({
                "id": str(ch.get("id", i + 1)),
                "title": ch.get("title", f"Chapter {i + 1}"),
                "order": i + 1,
                "paragraphs": paragraphs,
            })

        if not chapters:
            return StructuredText(source=self._make_source(book_id, url))

        content_type = "book_with_chapters" if len(chapters) > 1 else "single_chapter"

        meta = metadata or {}
        title = meta.get("title", "")
        meta_dict = {}
        if meta.get("author"):
            meta_dict["authors"] = [{"name": meta["author"]}]
        if meta.get("dynasty"):
            meta_dict["dynasty"] = meta["dynasty"]
        if meta.get("category"):
            meta_dict["category"] = meta["category"]

        return StructuredText(
            source=self._make_source(book_id, url),
            title=title,
            content_type=content_type,
            metadata=meta_dict,
            chapters=chapters,
        )
