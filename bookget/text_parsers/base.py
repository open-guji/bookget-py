"""Base classes for structured text parsing.

StructuredText is the canonical intermediate format for all text resources.
Site-specific parsers convert raw adapter data into StructuredText,
which is then saved as structured.json and converted to other formats.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class StructuredText:
    """Structured text content from a site adapter.

    This is the canonical format saved as text/structured.json.
    All format conversions (Markdown, plain text, etc.) derive from this.
    """

    schema_version: str = "1.0"
    source: dict = field(default_factory=dict)
    title: str = ""
    content_type: str = "single_chapter"
    metadata: dict = field(default_factory=dict)
    chapters: list = field(default_factory=list)

    # Valid content_type values:
    #   single_chapter     - Single chapter/article (no chapter hierarchy)
    #   book_with_chapters - Multi-chapter book
    #   catalog_entries    - Catalog/bibliography (each paragraph is an entry)
    #   commentary         - Commentary text (main text + annotations)
    #   poetry_collection  - Poetry/verse collection

    VALID_CONTENT_TYPES = {
        "single_chapter",
        "book_with_chapters",
        "catalog_entries",
        "commentary",
        "poetry_collection",
    }

    def to_dict(self) -> dict:
        """Convert to a plain dict for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StructuredText":
        """Create from a dict (e.g. loaded from JSON)."""
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            source=data.get("source", {}),
            title=data.get("title", ""),
            content_type=data.get("content_type", "single_chapter"),
            metadata=data.get("metadata", {}),
            chapters=data.get("chapters", []),
        )

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty if valid)."""
        errors = []
        if self.content_type not in self.VALID_CONTENT_TYPES:
            errors.append(
                f"Invalid content_type: '{self.content_type}'. "
                f"Must be one of {self.VALID_CONTENT_TYPES}"
            )
        if not self.title:
            errors.append("title is required")
        if not self.chapters:
            errors.append("chapters list is empty")
        for i, ch in enumerate(self.chapters):
            if "paragraphs" not in ch:
                errors.append(f"chapters[{i}] missing 'paragraphs' field")
            elif not isinstance(ch["paragraphs"], list):
                errors.append(f"chapters[{i}].paragraphs must be a list")
        return errors


class BaseTextParser:
    """Base class for site-specific text parsers.

    Each site with text resources should have a parser that converts
    the adapter's raw API/HTML data into a StructuredText object.
    """

    site_id: str = ""

    async def parse(self, raw_data: dict, book_id: str, url: str, index_id: str = "") -> StructuredText:
        """Convert adapter raw data to structured text.
        
        Args:
            raw_data: Raw data from the adapter (API responses, parsed HTML, etc.)
            book_id: The book identifier (source)
            url: The original URL
            index_id: The global index ID

        Returns:
            StructuredText object ready for serialization
        """
        raise NotImplementedError

    def _make_source(self, book_id: str, url: str, index_id: str = "", **extra) -> dict:
        """Build the source metadata dict."""
        source = {
            "site": self.site_id,
            "url": url,
            "book_id": book_id,
            "index_id": index_id,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        source.update(extra)
        return source
