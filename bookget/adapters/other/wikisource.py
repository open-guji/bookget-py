# 维基文库 (Wikisource) Adapter
# https://zh.wikisource.org/

import re
from typing import List, Optional
from urllib.parse import unquote
import aiohttp
import asyncio

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...text_parsers.base import StructuredText
from ...text_parsers.wikisource_parser import WikisourceParser
from ...logger import logger
from ...exceptions import MetadataExtractionError, DownloadError


@AdapterRegistry.register
class WikisourceAdapter(BaseSiteAdapter):
    """
    Adapter for 维基文库 (zh.wikisource.org).

    Chinese Wikisource hosts public domain ancient Chinese texts
    under CC BY-SA license. Uses MediaWiki API.

    URL patterns:
    - Book page: https://zh.wikisource.org/wiki/論語
    - Chapter:   https://zh.wikisource.org/wiki/論語/學而第一
    - zh variant: https://zh.wikisource.org/zh-hant/論語
    """

    site_name = "维基文库"
    site_id = "wikisource"
    site_domains = ["zh.wikisource.org"]

    supports_iiif = False
    supports_images = False
    supports_text = True

    API_URL = "https://zh.wikisource.org/w/api.php"

    default_headers = {
        "Accept": "application/json",
        "User-Agent": "GujiPlatform/1.0 (https://github.com/open-guji; guji@example.com)",
    }

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    def extract_book_id(self, url: str) -> str:
        """
        Extract page title from URL.

        Returns the decoded page title (e.g., '論語' or '論語/學而第一').
        """
        # Match /wiki/PageTitle or /zh-hant/PageTitle etc.
        match = re.search(r'(?:/wiki/|/zh(?:-\w+)?/)(.+?)(?:\?|#|$)', url)
        if match:
            title = unquote(match.group(1))
            # Remove trailing slashes
            return title.rstrip('/')

        raise MetadataExtractionError(f"Could not extract page title from URL: {url}")

    async def get_metadata(self, book_id: str) -> BookMetadata:
        """Fetch metadata from MediaWiki API."""
        session = await self.get_session()

        # Get page info and categories
        params = {
            "action": "parse",
            "page": book_id,
            "prop": "categories|wikitext",
            "format": "json",
        }

        try:
            async with session.get(self.API_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                if "error" in data:
                    raise MetadataExtractionError(
                        f"API error: {data['error'].get('info', 'Unknown')}"
                    )

                parse_data = data.get("parse", {})
                return self._parse_metadata(parse_data, book_id)

        except aiohttp.ClientError as e:
            raise MetadataExtractionError(f"Failed to fetch metadata: {e}")

    def _parse_metadata(self, data: dict, book_id: str) -> BookMetadata:
        """Parse MediaWiki response into BookMetadata."""
        metadata = BookMetadata(source_id=book_id)

        title = data.get("title", book_id)
        if "/" in title:
            metadata.title = title.split("/")[0]
        else:
            metadata.title = title

        # Extract categories
        categories = data.get("categories", [])
        for cat in categories:
            cat_name = cat.get("*", "")
            if cat_name:
                metadata.subjects.append(cat_name)

        # Try to extract author from wikitext {{header}} template
        wikitext = data.get("wikitext", {}).get("*", "")
        author_match = re.search(
            r'(?:author|override_author)\s*=\s*\[\[(?:作者:)?([^|\]]+)',
            wikitext
        )
        if author_match:
            metadata.creators.append(Creator(name=author_match.group(1).strip()))

        metadata.rights = "Public Domain"
        metadata.license = "CC BY-SA 4.0"
        metadata.language = "lzh"  # Classical Chinese

        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Wikisource is text-only, no images."""
        return []

    async def get_structured_text(self, book_id: str) -> Optional[StructuredText]:
        """
        Fetch text from Wikisource as structured data.

        If the page has subpages (it's a book), fetch all subpages.
        If it's a single chapter page, fetch just that.
        """
        session = await self.get_session()
        parser = WikisourceParser()

        # Check if this is a book (has subpages) or a chapter
        if "/" in book_id:
            # This is a chapter page - fetch single page
            return await self._fetch_single_page(book_id, parser)
        else:
            # This might be a book - check for subpages
            subpages = await self._list_subpages(book_id)
            if subpages:
                return await self._fetch_book(book_id, subpages, parser)
            else:
                # No subpages - treat as single page
                return await self._fetch_single_page(book_id, parser)

    async def _list_subpages(self, book_title: str) -> List[dict]:
        """List all subpages of a book."""
        session = await self.get_session()
        subpages = []

        params = {
            "action": "query",
            "list": "allpages",
            "apprefix": f"{book_title}/",
            "aplimit": "500",
            "format": "json",
        }

        try:
            async with session.get(self.API_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                pages = data.get("query", {}).get("allpages", [])

                for page in pages:
                    title = page.get("title", "")
                    # Skip "全覽" (full text view) pages
                    if title.endswith("/全覽"):
                        continue
                    subpages.append({
                        "title": title,
                        "pageid": page.get("pageid", 0),
                    })

                return subpages

        except Exception as e:
            logger.warning(f"Failed to list subpages for {book_title}: {e}")
            return []

    async def _fetch_single_page(
        self, page_title: str, parser: WikisourceParser
    ) -> Optional[StructuredText]:
        """Fetch and parse a single wiki page."""
        wikitext = await self._fetch_wikitext(page_title)
        if not wikitext:
            return None

        url = f"https://zh.wikisource.org/wiki/{page_title}"
        return parser.parse_single_page(wikitext, page_title, page_title, url)

    async def _fetch_book(
        self, book_title: str, subpages: List[dict], parser: WikisourceParser
    ) -> Optional[StructuredText]:
        """Fetch all subpages of a book and build structured text."""
        delay = self.config.download.request_delay if self.config else 0.5

        # Fetch wikitext for each subpage (batch up to 50 per request)
        pages_data = []
        batch_size = 50

        for i in range(0, len(subpages), batch_size):
            batch = subpages[i:i + batch_size]
            titles = "|".join(p["title"] for p in batch)

            wikitext_map = await self._fetch_wikitext_batch(titles)

            for page in batch:
                title = page["title"]
                wt = wikitext_map.get(title, "")
                if wt:
                    pages_data.append({
                        "title": title,
                        "pageid": page.get("pageid", 0),
                        "wikitext": wt,
                    })

            if i + batch_size < len(subpages):
                await asyncio.sleep(delay)

        if not pages_data:
            return None

        logger.info(f"Fetched {len(pages_data)}/{len(subpages)} pages for {book_title}")

        url = f"https://zh.wikisource.org/wiki/{book_title}"
        return parser.parse_book(pages_data, book_title, book_title, url)

    async def _fetch_wikitext(self, page_title: str) -> Optional[str]:
        """Fetch wikitext for a single page."""
        session = await self.get_session()

        params = {
            "action": "query",
            "titles": page_title,
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
        }

        try:
            async with session.get(self.API_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                pages = data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    if page_id == "-1":
                        return None
                    revisions = page_data.get("revisions", [])
                    if revisions:
                        return revisions[0].get("slots", {}).get("main", {}).get("*", "")

                return None

        except Exception as e:
            logger.warning(f"Failed to fetch wikitext for {page_title}: {e}")
            return None

    async def _fetch_wikitext_batch(self, titles: str) -> dict:
        """Fetch wikitext for multiple pages (pipe-separated titles)."""
        session = await self.get_session()
        result = {}

        params = {
            "action": "query",
            "titles": titles,
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
        }

        try:
            async with session.get(self.API_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                pages = data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    if page_id == "-1":
                        continue
                    title = page_data.get("title", "")
                    revisions = page_data.get("revisions", [])
                    if revisions:
                        wt = revisions[0].get("slots", {}).get("main", {}).get("*", "")
                        if wt:
                            result[title] = wt

        except Exception as e:
            logger.warning(f"Failed to fetch wikitext batch: {e}")

        return result

    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
