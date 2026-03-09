# Hanchi (漢籍全文資料庫) Adapter
# https://hanchi.ihp.sinica.edu.tw/
#
# Supports the TTS (Text Transfer System) CGI-based interface used by
# Academia Sinica's Institute of History and Philology for classical Chinese texts.

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Callable
from urllib.parse import urlparse

import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, Creator
from ...models.manifest import (
    DownloadManifest, ManifestNode, NodeStatus, NodeType, ResourceKind,
)
from ...text_parsers.base import StructuredText
from ...text_parsers.hanchi_parser import HanchiParser
from ...logger import logger
from ...exceptions import MetadataExtractionError, AdapterError


@dataclass
class HanchiSession:
    """Holds the state for one Hanchi CGI session."""
    session_id: str
    cgi_path: str
    flag: str
    checksum: str


# Known CGI sub-databases and their ttsweb ini names.
# The session initialization URL pattern is:
#   /mqlc/ttsweb?@0:0:1:{ini_name}@@{random}
# which redirects to a SPAWN URL with a fresh session ID.
_CGI_CONFIGS: Dict[str, Dict[str, str]] = {
    "/mqlc/hanjishilu": {
        "ttsweb_path": "/mqlc/ttsweb",
        "ini_name": "hanjishilu",
    },
    "/ihpc/hanjiquery": {
        "ttsweb_path": "/ihpc/ttswebquery",
        "ini_name": "hanjiquery",
    },
    "/ihpc/ttswebquery": {
        "ttsweb_path": "/ihpc/ttswebquery",
        "ini_name": "hanjiquery",
    },
    "/ihpc/ttsweb": {
        "ttsweb_path": "/ihpc/ttsweb",
        "ini_name": "hanji",
    },
}

# Reverse lookup: slug (last component of CGI path) → full path
_SLUG_TO_CGI: Dict[str, str] = {
    path.rsplit("/", 1)[-1]: path for path in _CGI_CONFIGS
}


@AdapterRegistry.register
class HanchiAdapter(BaseSiteAdapter):
    """
    Adapter for 漢籍全文資料庫 (Hanchi Electronic Texts).

    Handles the TTS CGI-based interface at hanchi.ihp.sinica.edu.tw.
    This is a full-text database — the primary downloadable content
    is text, not images.

    URL example:
        https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^1440492097^802^^^30211001@@341159809
    """

    site_name = "漢籍全文資料庫 (Hanchi)"
    site_id = "hanchi"
    site_domains = ["hanchi.ihp.sinica.edu.tw"]

    supports_iiif = False
    supports_images = False
    supports_text = True
    supports_pdf = False

    BASE_URL = "https://hanchi.ihp.sinica.edu.tw"

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._hanchi_sessions: dict[str, HanchiSession] = {}  # cgi_path -> cached session
        self._session_lock = asyncio.Lock()

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    # ------------------------------------------------------------------
    # URL parsing
    # ------------------------------------------------------------------

    def extract_book_id(self, url: str) -> str:
        """Extract book identifier from a Hanchi URL.

        Returns ``"{cgi_slug}:{book_node_id}"``, e.g. ``"hanjishilu:30211001"``.

        For chapter-level URLs the node is mapped up to the book level
        automatically.
        """
        parsed = urlparse(url)
        cgi_slug = parsed.path.rsplit("/", 1)[-1]

        if cgi_slug not in _SLUG_TO_CGI:
            raise MetadataExtractionError(
                f"Unknown Hanchi CGI program: {cgi_slug} (from {url})")

        query = parsed.query

        # Normal URL: @{flag}^{sid}^{action}^^^{node_id}[^extra]@@{checksum}
        match = re.search(r'\^\^\^(\d+)', query)
        if match:
            node_id = match.group(1)
            book_node = self._node_to_book_node(node_id)
            return f"{cgi_slug}:{book_node}"

        # SPAWN URL: {flag}:{sid}:{action}:{ini}:::@SPAWN — no node
        if "@SPAWN" in query:
            raise MetadataExtractionError(
                f"SPAWN URL does not identify a specific book: {url}")

        raise MetadataExtractionError(
            f"Could not extract node ID from Hanchi URL: {url}")

    @staticmethod
    def _node_to_book_node(node_id: str) -> str:
        """Derive the book-level (prefix ``3``) node ID from any depth.

        Node IDs are hierarchically encoded::

            30211001                   book        (prefix 3, 7 core chars)
            402110010005               vol group   (prefix 4)
            5021100100050005           volume      (prefix 5)
            60211001000500050002       chapter     (prefix 6)

        The book portion is always ``3`` + the 7 characters after the
        leading depth digit.
        """
        if node_id.startswith("3"):
            return node_id
        core = node_id[1:8]
        return f"3{core}"

    def _parse_book_id(self, book_id: str) -> tuple[str, str]:
        """Split composite *book_id* into ``(cgi_slug, node_id)``."""
        if ":" in book_id:
            slug, node = book_id.split(":", 1)
            return slug, node
        raise MetadataExtractionError(
            f"Invalid Hanchi book ID format: {book_id}")

    @staticmethod
    def _slug_to_cgi_path(slug: str) -> str:
        path = _SLUG_TO_CGI.get(slug)
        if not path:
            raise MetadataExtractionError(
                f"Unknown Hanchi sub-database slug: {slug}")
        return path

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_or_spawn_session(self, cgi_path: str) -> HanchiSession:
        """Return a cached HanchiSession, spawning a new one if needed."""
        async with self._session_lock:
            if cgi_path in self._hanchi_sessions:
                return self._hanchi_sessions[cgi_path]
            hs = await self._spawn_session(cgi_path)
            self._hanchi_sessions[cgi_path] = hs
            return hs

    async def _spawn_session(self, cgi_path: str) -> HanchiSession:
        """Initialize a new CGI session.

        The Hanchi TTS system requires a two-step initialization:

        1. Request ``/mqlc/ttsweb?@0:0:1:hanjishilu@@{random}`` which
           returns an HTML redirect to a SPAWN URL containing a fresh
           session ID.
        2. Follow the SPAWN URL to load the actual page with valid
           session links.
        """
        import random as _random

        cfg = _CGI_CONFIGS.get(cgi_path, {})
        ttsweb_path = cfg.get("ttsweb_path", cgi_path)
        ini_name = cfg.get("ini_name", cgi_path.rsplit("/", 1)[-1])

        # Step 1: anti-proxy request → HTML with Refresh redirect
        rand = _random.random()
        init_url = f"{self.BASE_URL}{ttsweb_path}?@0:0:1:{ini_name}@@{rand}"

        session = await self.get_session()
        async with session.get(init_url) as response:
            init_html = await response.text()

        # Parse the Refresh redirect to extract the SPAWN URL
        # Pattern: URL=http://...hanjishilu?{flag}:{session_id}:{action}:{ini_path}:::@SPAWN
        spawn_match = re.search(
            r"URL='?([^'>\s]+@SPAWN)", init_html, re.IGNORECASE,
        )
        if not spawn_match:
            raise AdapterError(
                f"Failed to get SPAWN redirect from {init_url}")

        spawn_url = spawn_match.group(1)
        # The redirect URL may use http — upgrade to https
        spawn_url = spawn_url.replace("http://", "https://")

        # Step 2: follow the SPAWN URL to get the full page
        async with session.get(spawn_url) as response:
            html = await response.text()

        cgi_name = cgi_path.rsplit("/", 1)[-1]
        # Parse links embedded in the response to extract session params.
        # Links look like:  hanjishilu?@2^154692159^802^^^30211001@@546086581
        match = re.search(
            rf'{re.escape(cgi_name)}\?@(\d+)\^(\d+)\^\d+\^\^\^[^@]*@@(\d+)',
            html,
        )
        if not match:
            raise AdapterError(
                f"Failed to parse SPAWN response from {spawn_url}")

        return HanchiSession(
            session_id=match.group(2),
            cgi_path=cgi_path,
            flag=match.group(1),
            checksum=match.group(3),
        )

    def _build_url(self, hs: HanchiSession, action: int,
                   node_id: str = "", extra: str = "") -> str:
        """Build a CGI URL for the given action."""
        suffix = f"^{extra}" if extra else ""
        return (
            f"{self.BASE_URL}{hs.cgi_path}"
            f"?@{hs.flag}^{hs.session_id}"
            f"^{action}^^^{node_id}{suffix}@@{hs.checksum}"
        )

    def _update_checksum(self, hs: HanchiSession, html: str):
        """Refresh the session checksum from *html* response."""
        cgi_name = hs.cgi_path.rsplit("/", 1)[-1]
        checksums = re.findall(
            rf'{re.escape(cgi_name)}\?@\d+\^\d+\^\d+\^\^\^[^@]*@@(\d+)',
            html,
        )
        if checksums:
            hs.checksum = checksums[-1]

    @staticmethod
    async def _read_response(response: aiohttp.ClientResponse) -> str:
        """Read response body, tolerating encoding errors."""
        # The server declares utf-8 in <meta> but some pages contain
        # stray non-UTF-8 bytes in title attributes.  Fall back
        # gracefully rather than crashing.
        raw = await response.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")

    async def _request(self, hs: HanchiSession, action: int,
                       node_id: str = "", extra: str = "") -> str:
        """Make a request with automatic session-expiry recovery.

        Returns the HTML response body.
        """
        url = self._build_url(hs, action, node_id, extra)
        session = await self.get_session()

        async with session.get(url) as response:
            html = await self._read_response(response)

        # Detect session timeout (server may redirect to a SPAWN page).
        if "@SPAWN" in html or "連線逾時" in html:
            logger.info("Hanchi session expired, re-initializing…")
            new = await self._spawn_session(hs.cgi_path)
            hs.session_id = new.session_id
            hs.checksum = new.checksum
            hs.flag = new.flag

            url = self._build_url(hs, action, node_id, extra)
            async with session.get(url) as response:
                html = await self._read_response(response)

        self._update_checksum(hs, html)
        return html

    # ------------------------------------------------------------------
    # Tree traversal — discover all text-bearing nodes
    # ------------------------------------------------------------------

    async def _discover_chapters(
        self, hs: HanchiSession, book_node: str,
    ) -> list[dict]:
        """Expand the tree recursively to find all leaf chapter nodes.

        A *leaf* is any node that appears in the tree with an action-802
        link but does **not** itself have an expand (action-801) link that
        reveals further 802 children.

        Returns a list of ``{"node_id": str, "title": str}`` dicts in
        tree order.
        """
        chapters: list[dict] = []
        visited: set[str] = set()
        delay = self._get_request_delay()
        cgi_name = hs.cgi_path.rsplit("/", 1)[-1]
        # The depth prefix of the starting node.  Any node whose prefix
        # digit is <= this value is an ancestor/self and should be skipped.
        book_depth = int(book_node[0])

        async def _expand(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)

            if delay > 0:
                await asyncio.sleep(delay)

            html = await self._request(hs, action=801, node_id=node_id)

            # Collect all 802 links and 801 (expandable) links from this page.
            # 802 links:  hanjishilu?@1^sid^802^^^{nid}@@{cs} class=booktree
            content_links = re.findall(
                rf'{re.escape(cgi_name)}\?@\d+\^\d+\^802\^\^\^(\d+)@@\d+'
                r"[^>]*class=booktree[01][^>]*>"
                r"\s*<font\s+class=tree[^>]*>(?:<b>)?([^<]+)",
                html,
            )
            # 801 links:  hanjishilu?@1^sid^801^^^{nid}^...
            expandable_nodes = set(re.findall(
                rf'{re.escape(cgi_name)}\?@\d+\^\d+\^801\^\^\^(\d+)\^',
                html,
            ))

            for nid, title in content_links:
                title = title.strip()
                # Skip ancestor/self nodes that appear in the tree
                # breadcrumb (their depth prefix <= the starting node).
                if int(nid[0]) <= book_depth:
                    continue
                if nid in expandable_nodes:
                    # This node has children — recurse
                    await _expand(nid)
                else:
                    # Leaf node — collect it
                    if nid not in visited:
                        visited.add(nid)
                        chapters.append({"node_id": nid, "title": title})

        await _expand(book_node)
        return chapters

    # ------------------------------------------------------------------
    # Text fetching (friendly-print pages)
    # ------------------------------------------------------------------

    async def _fetch_chapter_text(
        self, hs: HanchiSession, node_id: str,
    ) -> Optional[dict]:
        """Fetch text for one chapter via the content page (action 802).

        Action 802 works without prior navigation context, unlike the
        friendly-print page (810) which requires the chapter to have
        been viewed first.
        """
        delay = self._get_request_delay()
        if delay > 0:
            await asyncio.sleep(delay)

        html = await self._request(hs, action=802, node_id=node_id)
        return self._parse_content_page(html)

    @staticmethod
    def _extract_pages(content: str) -> list[dict]:
        """Parse fontstyle content into a list of page dicts.

        Each page dict has the structure::

            {
                "page_number": "1",          # display number from <a name=PX>
                "image": "https://...",       # viewpdf URL or "" if absent
                "paragraphs": ["text", ...]
            }

        The content is split on ``<table class=page>`` boundaries.  The
        first segment (before the first page marker) is treated as page 0
        when it contains text, otherwise discarded.
        """
        # Convert collation-note spans into inline 【text:note】 markers,
        # and strip the preceding <a> icon link.
        content = re.sub(
            r'<a[^>]*onclick="q\d+[^"]*"[^>]*>.*?</a>\s*', '',
            content, flags=re.DOTALL,
        )
        def _convert_span(m: re.Match) -> str:
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            # 纯图片占位符不转成内联标记（图片链接已记录在 image 字段）
            if text == '圖':
                return ''
            return '【' + text + '】'

        content = re.sub(
            r'<span\s+id=q\d+[^>]*>(.*?)</span>',
            _convert_span,
            content, flags=re.DOTALL,
        )

        # Strip viewpdf links entirely — the URL is extracted separately
        # via img_match; leaving the <a> tag would leak its inner text
        # (e.g. "圖") into the paragraph content.
        content = re.sub(
            r'<a\s+class=viewpdf[^>]*>.*?</a>',
            '', content, flags=re.DOTALL | re.IGNORECASE,
        )

        # Split on page-separator tables, keeping the table HTML so we can
        # extract the page number from each separator.
        parts = re.split(r'(<table\s+class=page>.*?</table>)', content,
                         flags=re.DOTALL | re.IGNORECASE)

        pages: list[dict] = []
        current_page_number = ""
        current_image = ""
        pending_html = parts[0]  # content before the first page marker

        def _flush(html_chunk: str, page_num: str, img: str) -> None:
            """Extract paragraphs from an html chunk and append a page."""
            paragraphs: list[str] = []

            # headings
            for m in re.finditer(r'<h3>(.*?)</h3>', html_chunk, re.DOTALL):
                text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                text = re.sub(r'[\r\n\t]+', '', text).strip()
                if text:
                    paragraphs.append(text)

            # divs
            for m in re.finditer(r'<div[^>]*>(.*?)</div>', html_chunk, re.DOTALL):
                inner = m.group(1)
                # capture viewpdf URL inside divs (second page and beyond
                # embed the image link inside the opening div)
                if not img:
                    vm = re.search(
                        r"hanji_book\?([^\s'\"]+)", inner)
                    if vm:
                        img = f"https://hanchi.ihp.sinica.edu.tw/mqlc/hanji_book?{vm.group(1)}"
                text = re.sub(r'<[^>]+>', '', inner).strip()
                text = re.sub(r'[\r\n\t]+', '', text).strip()
                if text:
                    paragraphs.append(text)

            if paragraphs or img:
                pages.append({
                    "page_number": page_num,
                    "image": img,
                    "paragraphs": paragraphs,
                })

        i = 1
        while i < len(parts):
            table_html = parts[i]
            following_html = parts[i + 1] if i + 1 < len(parts) else ""

            # page number: <table ...><a name=PX></a>DISPLAY_NUM</table>
            # the anchor tag may be self-closing or paired; the number follows it
            pn_match = re.search(
                r'<a\s+name=P\d+[^>]*>(?:</a>)?\s*([^\s<]+)', table_html)
            new_page_number = pn_match.group(1).strip() if pn_match else ""

            # image URL from the viewpdf link that immediately follows the table
            # (appears before the first div on that page)
            img_match = re.search(
                r"<a\s+class=viewpdf[^>]*hanji_book\?([^\s'\"]+)",
                following_html,
            )
            new_image = (
                f"https://hanchi.ihp.sinica.edu.tw/mqlc/hanji_book?{img_match.group(1)}"
                if img_match else ""
            )

            # flush the accumulated chunk under the previous page header
            _flush(pending_html, current_page_number, current_image)

            current_page_number = new_page_number
            current_image = new_image
            pending_html = following_html
            i += 2

        # flush the last segment
        _flush(pending_html, current_page_number, current_image)
        return pages

    @staticmethod
    def _parse_content_page(html: str) -> Optional[dict]:
        """Extract text from a regular content page (action 802).

        Returns ``{"title": str, "breadcrumb": str, "pages": [...]}``
        or *None* if the page has no extractable text.
        """
        result: dict = {"title": "", "breadcrumb": "", "pages": []}

        # Breadcrumb from  <a class=gobookmark ...>史／編年／明實錄／太祖(P.1)</a>
        bc_match = re.search(r'class=gobookmark[^>]*>([^<]+)</a>', html)
        if bc_match:
            breadcrumb = bc_match.group(1).strip()
            result["breadcrumb"] = breadcrumb
            parts = breadcrumb.split("／")
            chapter_title = parts[-1].strip() if parts else ""
            chapter_title = re.sub(r'\s*\(P\.[^)]*\)\s*$', '', chapter_title)
            result["title"] = chapter_title

        # Text content in <SPAN id=fontstyle> … </SPAN>
        fontstyle_match = re.search(
            r'<SPAN\s+id=fontstyle[^>]*>(.*)</SPAN>',
            html, re.DOTALL,
        )
        if not fontstyle_match:
            return None

        pages = HanchiAdapter._extract_pages(fontstyle_match.group(1))
        if not pages:
            return None

        result["pages"] = pages
        return result

    @staticmethod
    def _parse_friendly_print(html: str) -> Optional[dict]:
        """Extract text from a friendly-print (action 810) page.

        Returns ``{"title": str, "breadcrumb": str, "pages": [...]}``
        or *None* if the page has no extractable text.
        """
        result: dict = {"title": "", "breadcrumb": "", "pages": []}

        # Breadcrumb / chapter title.
        title_match = re.search(
            r'<font[^>]*color:#0066CC[^>]*>\s*([^<]+)',
            html, re.IGNORECASE,
        )
        if title_match:
            breadcrumb = title_match.group(1).strip()
            if breadcrumb:
                result["breadcrumb"] = breadcrumb
                parts = breadcrumb.split("／")
                chapter_title = parts[-1].strip() if parts else ""
                chapter_title = re.sub(r'\s*\(P\.[^)]*\)\s*$', '', chapter_title)
                result["title"] = chapter_title

        fontstyle_match = re.search(
            r'<SPAN\s+id=fontstyle[^>]*>(.*)</SPAN>',
            html, re.DOTALL,
        )
        if not fontstyle_match:
            return None

        pages = HanchiAdapter._extract_pages(fontstyle_match.group(1))
        if not pages:
            return None

        result["pages"] = pages
        return result

    # ------------------------------------------------------------------
    # Metadata parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_book_metadata(html: str, book_id: str) -> BookMetadata:
        """Parse metadata from a book-level (action 802) page."""
        metadata = BookMetadata(source_id=book_id)

        # Category / breadcrumb from  <a class=gobookmark ...>史／編年／明實錄</a>
        bc_match = re.search(r'class=gobookmark[^>]*>([^<]+)</a>', html)
        if bc_match:
            breadcrumb = bc_match.group(1).strip()
            metadata.category = breadcrumb
            parts = breadcrumb.split("／")
            raw_title = parts[-1].strip() if parts else ""
            # Remove page marker
            metadata.title = re.sub(r'\s*\(P\.\d+\)\s*$', '', raw_title)

        # Publisher info from  <img ...imgbook... title='出版地 : 出版者, 年代，校勘'>
        pub_match = re.search(r"<img[^>]*imgbook[^>]*title='([^']+)'", html)
        if pub_match:
            pub_info = pub_match.group(1).strip()
            metadata.raw_metadata["publisher_info"] = pub_info
            # Split on ，(full-width comma) for collation notes
            pub_parts = pub_info.split("，")
            if pub_parts:
                lp = pub_parts[0]
                lp_match = re.match(
                    r'(.+?)\s*[:：]\s*(.+?)\s*[,，]\s*(.+)', lp)
                if lp_match:
                    metadata.place = lp_match.group(1).strip()
                    metadata.publisher = lp_match.group(2).strip()
                    metadata.date = lp_match.group(3).strip()
            if len(pub_parts) > 1:
                metadata.notes.append(pub_parts[1].strip())

        metadata.language = "lzh"
        metadata.collection_unit = "中央研究院歷史語言研究所"
        return metadata

    # ------------------------------------------------------------------
    # Public API — BaseSiteAdapter interface
    # ------------------------------------------------------------------

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        cgi_slug, node_id = self._parse_book_id(book_id)
        cgi_path = self._slug_to_cgi_path(cgi_slug)

        hs = await self._spawn_session(cgi_path)
        html = await self._request(hs, action=802, node_id=node_id)

        metadata = self._parse_book_metadata(html, book_id)
        metadata.index_id = index_id
        metadata.source_url = self._build_url(hs, 802, node_id)
        metadata.source_site = self.site_id
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        return []

    async def get_structured_text(
        self, book_id: str, index_id: str = "",
        progress_callback: Callable[[int, int], None] = None,
    ) -> Optional[StructuredText]:
        """Download full text by traversing the chapter tree.

        1. SPAWN a fresh session
        2. Fetch book-page metadata
        3. Discover all leaf chapter nodes via tree expansion
        4. Fetch each chapter's text via the friendly-print page
        5. Assemble into StructuredText
        """
        cgi_slug, book_node = self._parse_book_id(book_id)
        cgi_path = self._slug_to_cgi_path(cgi_slug)

        hs = await self._spawn_session(cgi_path)
        logger.info(f"Hanchi session initialized (sid={hs.session_id})")

        # Book metadata
        html = await self._request(hs, action=802, node_id=book_node)
        book_meta = self._parse_book_metadata(html, book_id)
        meta_dict = {
            "title": book_meta.title,
            "category": book_meta.category,
            "publisher": book_meta.publisher,
            "place": book_meta.place,
            "date": book_meta.date,
            "notes": book_meta.notes,
        }

        # Discover chapters
        logger.info(f"Discovering chapters for '{book_meta.title}'…")
        chapters = await self._discover_chapters(hs, book_node)

        if not chapters:
            logger.warning(f"No chapters found for {book_id}")
            return None

        logger.info(f"Found {len(chapters)} chapters, fetching text…")

        # Fetch each chapter
        total = len(chapters)
        chapter_data: list[dict] = []
        for i, ch in enumerate(chapters):
            text = await self._fetch_chapter_text(hs, ch["node_id"])
            if text:
                chapter_data.append({
                    "node_id": ch["node_id"],
                    "title": ch.get("title") or text.get("title", f"Chapter {i+1}"),
                    "breadcrumb": text.get("breadcrumb", ""),
                    "pages": text.get("pages", []),
                })
                logger.info(
                    f"  [{i+1}/{total}] {ch.get('title', ch['node_id'])}")
            if progress_callback:
                progress_callback(i + 1, total)

        if not chapter_data:
            return None

        parser = HanchiParser()
        source_url = f"{self.BASE_URL}{cgi_path}"
        return parser.parse_book(
            chapter_data, meta_dict, book_id, source_url, index_id=index_id,
        )

    # ------------------------------------------------------------------
    # Incremental discovery & download (new API)
    # ------------------------------------------------------------------

    async def discover_structure(
        self, book_id: str, index_id: str = "",
        depth: int = 1,
        progress_callback: Callable[[str, str], None] = None,
    ) -> DownloadManifest:
        """Discover Hanchi book structure progressively.

        depth=1:  top-level sections only (太祖, 太宗, ...)
        depth=2:  sections + their volume/chapter lists
        depth=-1: full recursive discovery (slow for large books)
        """
        cgi_slug, book_node = self._parse_book_id(book_id)
        cgi_path = self._slug_to_cgi_path(cgi_slug)

        hs = await self._spawn_session(cgi_path)
        logger.info(f"Hanchi session initialized (sid={hs.session_id})")

        # Book metadata
        html = await self._request(hs, action=802, node_id=book_node)
        book_meta = self._parse_book_metadata(html, book_id)

        manifest = DownloadManifest(
            book_id=book_id,
            source_url=f"{self.BASE_URL}{cgi_path}",
            source_site=self.site_id,
            title=book_meta.title,
            metadata={
                "category": book_meta.category or "",
                "publisher": book_meta.publisher or "",
                "place": book_meta.place or "",
                "date": book_meta.date or "",
            },
        )

        root = ManifestNode(
            id=book_node,
            title=book_meta.title,
            node_type=NodeType.ROOT,
            status=NodeStatus.DISCOVERED,
            resource_kind=ResourceKind.TEXT,
        )

        logger.info(f"Discovering structure for '{book_meta.title}' (depth={depth})…")
        await self._expand_hanchi_node(hs, root, book_node, depth, progress_callback)

        manifest.root = root
        manifest.discovery_complete = (depth == -1)
        return manifest

    async def _expand_hanchi_node(
        self, hs: HanchiSession, node: ManifestNode,
        node_id: str, remaining_depth: int,
        progress_callback: Callable = None,
    ):
        """Expand a Hanchi tree node to discover its children."""
        if remaining_depth == 0:
            node.expandable = True
            return

        delay = self._get_request_delay()
        cgi_name = hs.cgi_path.rsplit("/", 1)[-1]
        parent_depth = int(node_id[0])

        if delay > 0:
            await asyncio.sleep(delay)

        html = await self._request(hs, action=801, node_id=node_id)

        # Parse 802 (content) and 801 (expandable) links, capturing checksum
        content_links = re.findall(
            rf'{re.escape(cgi_name)}\?@\d+\^\d+\^802\^\^\^(\d+)@@(\d+)'
            r"[^>]*class=booktree[01][^>]*>"
            r"\s*<font\s+class=tree[^>]*>(?:<b>)?([^<]+)",
            html,
        )
        expandable_nodes = set(re.findall(
            rf'{re.escape(cgi_name)}\?@\d+\^\d+\^801\^\^\^(\d+)\^',
            html,
        ))

        seen = set()
        first_child_nid: Optional[str] = None
        children_to_add: list[ManifestNode] = []
        for nid, checksum, title in content_links:
            if nid in seen:
                continue
            seen.add(nid)
            title = title.strip()

            # Ancestor/self breadcrumb nodes — skip
            if int(nid[0]) <= parent_depth:
                continue

            is_expandable = nid in expandable_nodes
            child_type = NodeType.SECTION if is_expandable else NodeType.CHAPTER

            child = ManifestNode(
                id=nid,
                title=title,
                node_type=child_type,
                status=NodeStatus.PENDING if is_expandable else NodeStatus.DISCOVERED,
                resource_kind=ResourceKind.TEXT,
                expandable=is_expandable,
                source_data={"node_id": nid},
            )

            if is_expandable and remaining_depth != 0:
                next_depth = remaining_depth - 1 if remaining_depth > 0 else -1
                await self._expand_hanchi_node(
                    hs, child, nid, next_depth, progress_callback)

            if first_child_nid is None:
                first_child_nid = nid
            children_to_add.append(child)

            if progress_callback:
                progress_callback("node_discovered", title)

        # Check whether the parent node has its own unique content by
        # comparing actual text with the first child.  As soon as any
        # difference is found we know the parent has independent content.
        if children_to_add and first_child_nid:
            has_own_content = await self._parent_has_own_content(
                hs, node_id, first_child_nid)
            if has_own_content:
                self_leaf = ManifestNode(
                    id=f"{node.id}_self",
                    title=node.title,
                    node_type=NodeType.CHAPTER,
                    status=NodeStatus.DISCOVERED,
                    resource_kind=ResourceKind.TEXT,
                    source_data={"node_id": node.source_data.get("node_id", node.id)},
                )
                node.children.append(self_leaf)

        for child in children_to_add:
            node.children.append(child)

        node.children_count = len(node.children)
        # Count text leaves
        leaves = node.get_leaf_nodes()
        node.text_count = sum(1 for n in leaves if n.id != node.id)
        if node.children:
            node.status = NodeStatus.DISCOVERED

    async def _parent_has_own_content(
        self, hs: HanchiSession, parent_nid: str, first_child_nid: str,
    ) -> bool:
        """Compare actual text of parent and first child to decide
        whether the parent has its own unique content.

        Returns True as soon as any difference in paragraph text is found.
        """
        parent_text = await self._fetch_chapter_text(hs, parent_nid)
        child_text = await self._fetch_chapter_text(hs, first_child_nid)

        parent_paras = self._collect_paragraphs(parent_text)
        child_paras = self._collect_paragraphs(child_text)

        if len(parent_paras) != len(child_paras):
            return True
        for p, c in zip(parent_paras, child_paras):
            if p != c:
                return True
        return False

    @staticmethod
    def _collect_paragraphs(text_data: Optional[dict]) -> list[str]:
        """Flatten all paragraph strings from parsed chapter text."""
        if not text_data or not text_data.get("pages"):
            return []
        result: list[str] = []
        for page in text_data["pages"]:
            result.extend(page.get("paragraphs", []))
        return result

    async def expand_node(
        self, book_id: str, manifest: DownloadManifest,
        node_id: str, depth: int = 1,
        progress_callback: Callable = None,
    ) -> Optional[ManifestNode]:
        """Expand a specific node in an existing manifest."""
        node = manifest.find_node(node_id)
        if not node or not node.expandable:
            return node

        cgi_slug, _ = self._parse_book_id(book_id)
        cgi_path = self._slug_to_cgi_path(cgi_slug)
        hs = await self._spawn_session(cgi_path)

        source_nid = node.source_data.get("node_id", node.id)
        await self._expand_hanchi_node(hs, node, source_nid, depth, progress_callback)
        return node

    async def download_node(
        self, book_id: str, node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """Download text for a single Hanchi chapter node."""
        cgi_slug, _ = self._parse_book_id(book_id)
        cgi_path = self._slug_to_cgi_path(cgi_slug)
        hs = await self._get_or_spawn_session(cgi_path)

        source_nid = node.source_data.get("node_id", node.id)
        node.status = NodeStatus.DOWNLOADING

        source_url = self._build_url(hs, 802, source_nid)
        text = await self._fetch_chapter_text(hs, source_nid)
        if text:
            dest_dir = Path(output_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)

            safe_title = re.sub(r'[<>:"/\\|?*]', '_', node.title).strip()[:80]
            filename = f"{safe_title}.json"
            chapter_file = dest_dir / filename

            chapter_data = {
                "node_id": source_nid,
                "source_url": source_url,
                "title": node.title or text.get("title", ""),
                "breadcrumb": text.get("breadcrumb", ""),
                "pages": text.get("pages", []),
            }
            chapter_file.write_text(
                json.dumps(chapter_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            node.status = NodeStatus.COMPLETED
            node.downloaded_items = 1
            node.total_items = 1
            node.local_path = filename
        else:
            node.status = NodeStatus.FAILED
            node.failed_items = 1

        if progress_callback:
            progress_callback(1, 1)
        return node

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_request_delay(self) -> float:
        if self.config and hasattr(self.config, "download"):
            return self.config.download.request_delay
        return 1.0

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
