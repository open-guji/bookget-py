# Wikisource (维基文库) text parser

import re
from typing import List, Optional
from .base import StructuredText, BaseTextParser


class WikisourceParser(BaseTextParser):
    """
    Parser for zh.wikisource.org wikitext content.

    Converts MediaWiki wikitext to StructuredText by:
    1. Extracting text from <onlyinclude> blocks if present
    2. Stripping {{header2}} navigation templates
    3. Handling {{另}} and {{另2}} variant templates
    4. Cleaning wiki markup (links, bold, HTML tags)
    """

    site_id = "wikisource"

    def parse_book(
        self,
        pages: List[dict],
        book_title: str,
        book_id: str,
        url: str,
    ) -> StructuredText:
        """
        Parse multiple subpages into a book StructuredText.

        Args:
            pages: List of dicts with 'title' and 'wikitext' keys.
            book_title: The book's main title.
            book_id: Book identifier (page title).
            url: Original URL.
        """
        chapters = []
        for i, page in enumerate(pages):
            wikitext = page.get("wikitext", "")
            title = page.get("title", f"Chapter {i + 1}")

            # Extract chapter title (remove book prefix)
            if "/" in title:
                chapter_title = title.split("/", 1)[1]
            else:
                chapter_title = title

            # Parse wikitext to plain text paragraphs
            paragraphs = self._wikitext_to_paragraphs(wikitext)
            if not paragraphs:
                continue

            chapters.append({
                "id": str(page.get("pageid", i + 1)),
                "title": chapter_title,
                "order": i + 1,
                "source_url": f"https://zh.wikisource.org/wiki/{title}",
                "paragraphs": paragraphs,
            })

        if not chapters:
            return StructuredText(source=self._make_source(book_id, url))

        content_type = "book_with_chapters" if len(chapters) > 1 else "single_chapter"

        return StructuredText(
            source=self._make_source(book_id, url),
            title=book_title,
            content_type=content_type,
            metadata={"license": "CC BY-SA 4.0"},
            chapters=chapters,
        )

    def parse_single_page(
        self,
        wikitext: str,
        title: str,
        book_id: str,
        url: str,
    ) -> StructuredText:
        """Parse a single wiki page into StructuredText."""
        paragraphs = self._wikitext_to_paragraphs(wikitext)

        # Extract section name
        if "/" in title:
            section_name = title.split("/", 1)[1]
            book_name = title.split("/", 1)[0]
        else:
            section_name = title
            book_name = title

        chapters = []
        if paragraphs:
            chapters.append({
                "id": book_id,
                "title": section_name,
                "order": 1,
                "paragraphs": paragraphs,
            })

        return StructuredText(
            source=self._make_source(book_id, url),
            title=book_name,
            content_type="single_chapter",
            metadata={"license": "CC BY-SA 4.0"},
            chapters=chapters,
        )

    def _wikitext_to_paragraphs(self, wikitext: str) -> List[str]:
        """Convert wikitext to a list of plain text paragraphs."""
        if not wikitext:
            return []

        text = wikitext

        # Extract from <onlyinclude> blocks if present
        only_include = re.findall(
            r'<onlyinclude>(.*?)</onlyinclude>', text, re.DOTALL
        )
        if only_include:
            text = "\n".join(only_include)

        # Strip {{header2|...}} template (may span multiple lines)
        text = re.sub(r'\{\{header2[^}]*\}\}', '', text, flags=re.DOTALL)
        # Strip other header templates
        text = re.sub(r'\{\{header[^}]*\}\}', '', text, flags=re.DOTALL)

        # Handle {{另|main|alt}} → keep main text
        text = re.sub(r'\{\{另2?\|([^|}]+)\|[^}]*\}\}', r'\1', text)

        # Handle {{ruby|base|ruby_text}} → keep base
        text = re.sub(r'\{\{ruby\|([^|}]+)\|[^}]*\}\}', r'\1', text)

        # Strip remaining simple templates {{...}}
        text = re.sub(r'\{\{[^}]*\}\}', '', text)

        # Remove category links (before wiki link processing)
        text = re.sub(r'\[\[Category:[^\]]*\]\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[\[分類:[^\]]*\]\]', '', text)

        # Handle wiki links [[target|display]] → display
        text = re.sub(r'\[\[[^\]|]+\|([^\]]+)\]\]', r'\1', text)
        # Handle wiki links [[target]] → target
        text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)

        # Strip HTML tags but keep content
        text = re.sub(r'</?(?:div|span|poem|center|br\s*/?)(?:\s[^>]*)?>', '', text)
        text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.DOTALL)
        text = re.sub(r'<ref[^>]*/>', '', text)
        # Remove onlyinclude/noinclude tags themselves
        text = re.sub(r'</?(?:onlyinclude|noinclude|includeonly)>', '', text)

        # Remove bold/italic wiki markup
        text = re.sub(r"'{2,3}", '', text)

        # Remove leading colons (used for indentation in poetry)
        text = re.sub(r'^:+', '', text, flags=re.MULTILINE)

        # Remove Chinese variant conversion markup -{...}-
        text = re.sub(r'-\{[^}]*\}-', '', text)

        # Split into paragraphs by blank lines
        raw_paragraphs = re.split(r'\n\s*\n', text)

        result = []
        for para in raw_paragraphs:
            # Clean up whitespace
            lines = [line.strip() for line in para.split('\n') if line.strip()]
            if lines:
                # Join lines within a paragraph
                combined = '\n'.join(lines)
                if combined.strip():
                    result.append(combined.strip())

        return result
