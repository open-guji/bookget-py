# Search models for site adapter search functionality

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchResult:
    """A single search result from a site adapter."""

    title: str
    page_id: int = 0
    url: str = ""
    snippet: str = ""
    is_disambiguation: bool = False
    versions: List["SearchResult"] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    source_site: str = ""

    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "page_id": self.page_id,
            "url": self.url,
            "snippet": self.snippet,
            "source_site": self.source_site,
        }
        if self.is_disambiguation:
            d["is_disambiguation"] = True
        if self.versions:
            d["versions"] = [v.to_dict() for v in self.versions]
        if self.categories:
            d["categories"] = self.categories
        return d


@dataclass
class SearchResponse:
    """Response from a site adapter search operation."""

    query: str
    results: List[SearchResult] = field(default_factory=list)
    total_hits: int = 0
    has_more: bool = False
    continuation: str = ""

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "total_hits": self.total_hits,
            "has_more": self.has_more,
            "continuation": self.continuation,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass
class MatchedResource:
    """A single resource matched by exact title + author matching.

    Corresponds to a resource entry in the book index:
    {id, name, url, type, details}.
    """

    id: str          # e.g. "wikisource", "wikisource-siku"
    name: str        # e.g. "维基文库", "维基文库（四庫全書本）"
    url: str         # e.g. "https://zh.wikisource.org/wiki/周易"
    type: str = "text"
    details: str = ""

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "type": self.type,
        }
        if self.details:
            d["details"] = self.details
        return d


@dataclass
class MatchResponse:
    """Response from match_book: exact title + author matching."""

    title: str
    authors: List[str] = field(default_factory=list)
    results: List[MatchedResource] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "results": [r.to_dict() for r in self.results],
        }
