# 维基文库 (Wikisource) Adapter
# https://zh.wikisource.org/

import json
import re
from pathlib import Path
from typing import List, Optional, Callable
from urllib.parse import unquote
import aiohttp
import asyncio

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...models.manifest import (
    DownloadManifest, ManifestNode, NodeStatus, NodeType, ResourceKind,
)
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

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
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

    async def discover_structure(
        self,
        book_id: str,
        index_id: str = "",
        depth: int = 1,
        progress_callback: Callable[[str, str], None] = None,
    ) -> DownloadManifest:
        """Discover book structure by listing all subpages via MediaWiki API.

        Automatically handles both flat and nested subpage structures:
          Flat (e.g. 論語/學而第一):
            ROOT → CHAPTER × N
          Nested (e.g. 某書/卷一/章一):
            ROOT → SECTION × M → CHAPTER × N

        Each leaf CHAPTER node stores its full page title in
        source_data["page_title"] for use by download_node().

        Custom page filtering / grouping:
            Set ``self.page_filter`` to a callable
            ``(page_title: str, book_id: str) -> bool`` to exclude pages.
            Set ``self.group_key`` to a callable
            ``(rel_path: str) -> str | None`` that returns a section name
            for grouping, or None to keep the original hierarchy.
        """
        metadata = await self.get_metadata(book_id, index_id=index_id)

        manifest = DownloadManifest(
            book_id=book_id,
            source_url=f"https://zh.wikisource.org/wiki/{book_id}",
            source_site=self.site_id,
            title=metadata.title,
            metadata={
                k: v for k, v in metadata.to_dict().items()
                if k in ("title", "creators", "dynasty", "category", "language") and v
            },
        )

        root = ManifestNode(
            id=book_id,
            title=metadata.title,
            node_type=NodeType.ROOT,
            status=NodeStatus.DISCOVERED,
            resource_kind=ResourceKind.TEXT,
        )

        subpages = await self._list_subpages(book_id)

        # Apply page_filter if set
        page_filter = getattr(self, "page_filter", None)
        if page_filter:
            before = len(subpages)
            subpages = [p for p in subpages if page_filter(p["title"], book_id)]
            logger.info(f"Page filter: {before} → {len(subpages)} pages")

        if not subpages:
            # No subpages: treat the main page itself as a single chapter
            root.children.append(ManifestNode(
                id=book_id,
                title=metadata.title,
                node_type=NodeType.CHAPTER,
                status=NodeStatus.DISCOVERED,
                resource_kind=ResourceKind.TEXT,
                text_count=1,
                total_items=1,
                source_data={"page_title": book_id},
            ))
        else:
            group_key = getattr(self, "group_key", None)
            self._build_subpage_tree(
                root, book_id, subpages, progress_callback,
                group_key=group_key,
            )

        root.children_count = len(root.children)
        root.text_count = sum(1 for n in root.get_text_nodes())
        manifest.root = root
        manifest.discovery_complete = True

        logger.info(
            f"Wikisource: discovered {root.text_count} leaf chapters "
            f"for '{book_id}'"
        )
        return manifest

    def _build_subpage_tree(
        self,
        root: ManifestNode,
        book_id: str,
        subpages: List[dict],
        progress_callback: Callable[[str, str], None] = None,
        group_key: Callable[[str], Optional[str]] = None,
    ) -> None:
        """Build a manifest tree from a flat list of subpage dicts.

        Subpage titles have the form ``{book_id}/{path}``.  The ``{path}``
        may be one segment ("卷001") or multiple ("卷一/章一").  This
        method groups multi-segment paths under intermediate SECTION nodes
        so the tree mirrors the actual URL hierarchy.

        If *group_key* is provided, it overrides the natural "/" hierarchy.
        The callable receives the relative path (e.g. "卷001") and returns
        a section name (e.g. "經部") or None (attach to root directly).
        This allows custom grouping of flat subpages without requiring
        them to have a nested URL structure.
        """
        section_nodes: dict[str, ManifestNode] = {}
        prefix = book_id + "/"
        chapter_seq = 0  # sequential counter for juan numbering

        for page in subpages:
            full_title = page["title"]
            rel = full_title[len(prefix):] if full_title.startswith(prefix) else full_title

            # Determine hierarchy: custom group_key overrides URL structure
            if group_key:
                group = group_key(rel)
                parts = [group, rel] if group else [rel]
            else:
                parts = rel.split("/")

            if len(parts) == 1:
                chapter_seq += 1
                node = ManifestNode(
                    id=rel,
                    title=parts[0],
                    node_type=NodeType.CHAPTER,
                    status=NodeStatus.DISCOVERED,
                    resource_kind=ResourceKind.TEXT,
                    text_count=1,
                    total_items=1,
                    source_data={
                        "page_title": full_title,
                        "juan_index": chapter_seq,
                    },
                )
                root.children.append(node)
            else:
                parent = root
                for depth_idx, segment in enumerate(parts[:-1]):
                    section_rel = "/".join(parts[:depth_idx + 1])
                    if section_rel not in section_nodes:
                        section_node = ManifestNode(
                            id=section_rel,
                            title=segment,
                            node_type=NodeType.SECTION,
                            status=NodeStatus.DISCOVERED,
                            resource_kind=ResourceKind.TEXT,
                        )
                        section_nodes[section_rel] = section_node
                        parent.children.append(section_node)
                    parent = section_nodes[section_rel]

                chapter_seq += 1
                leaf = ManifestNode(
                    id=rel,
                    title=parts[-1],
                    node_type=NodeType.CHAPTER,
                    status=NodeStatus.DISCOVERED,
                    resource_kind=ResourceKind.TEXT,
                    text_count=1,
                    total_items=1,
                    source_data={
                        "page_title": full_title,
                        "juan_index": chapter_seq,
                    },
                )
                parent.children.append(leaf)

            if progress_callback:
                progress_callback("chapter", full_title)

        # Write total chapter count into each leaf so download_node
        # can determine the filename zero-padding width.
        for leaf in root.get_text_nodes():
            leaf.source_data["juan_total"] = chapter_seq

        for node in section_nodes.values():
            node.children_count = len(node.children)

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
        """List all subpages of a book, with pagination support."""
        session = await self.get_session()
        subpages = []

        params: dict = {
            "action": "query",
            "list": "allpages",
            "apprefix": f"{book_title}/",
            "aplimit": "500",
            "format": "json",
        }

        try:
            while True:
                async with session.get(self.API_URL, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()
                    pages = data.get("query", {}).get("allpages", [])

                    for page in pages:
                        title = page.get("title", "")
                        if title.endswith("/全覽"):
                            continue
                        subpages.append({
                            "title": title,
                            "pageid": page.get("pageid", 0),
                        })

                    # Check for continuation
                    cont = data.get("continue", {}).get("apcontinue")
                    if not cont:
                        break
                    params["apcontinue"] = cont

        except Exception as e:
            logger.warning(f"Failed to list subpages for {book_title}: {e}")

        return subpages

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

    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """Download raw wikitext for a single Wikisource chapter node.

        Saves the unprocessed wikitext as-is, preserving all markup,
        line breaks, and templates.  Downstream scripts handle parsing.
        """
        node.status = NodeStatus.DOWNLOADING

        page_title = node.source_data.get("page_title") or book_id

        try:
            wikitext = await self._fetch_wikitext(page_title)
        except Exception as e:
            logger.error(f"Failed to fetch wikitext for '{page_title}': {e}")
            node.status = NodeStatus.FAILED
            node.failed_items = 1
            return node

        if not wikitext:
            node.status = NodeStatus.FAILED
            node.failed_items = 1
            return node

        dest_dir = Path(output_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        juan_index = node.source_data.get("juan_index")
        if juan_index:
            total = node.source_data.get("juan_total", 0)
            width = max(2, len(str(total))) if total else 2
            filename = f"juan{juan_index:0{width}d}.json"
        else:
            filename = "raw.wikisource.json"
        out_file = dest_dir / filename

        # Extract chapter title from page_title
        chapter_title = page_title.split("/")[-1] if "/" in page_title else page_title

        data = {
            "title": chapter_title,
            "page_title": page_title,
            "source_url": f"https://zh.wikisource.org/wiki/{page_title}",
            "content": wikitext,
        }

        out_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        node.status = NodeStatus.COMPLETED
        node.downloaded_items = 1
        node.total_items = 1
        node.local_path = filename

        if progress_callback:
            progress_callback(1, 1)

        return node

    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
