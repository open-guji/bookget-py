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
from ...models.search import SearchResult, SearchResponse
from ...text_parsers.base import StructuredText
from ...text_parsers.wikisource_parser import WikisourceParser
from ...models.search import MatchedResource
from ...logger import logger
from ...exceptions import MetadataExtractionError, DownloadError

# 维基文库常见特殊卷名 → 拼音文件名前缀映射
# 格式: 正则模式 → (前缀, 是否保留尾部数字)
_SPECIAL_JUAN_PATTERNS: List[tuple] = [
    (re.compile(r'^卷首(\d+)$'), 'juanshou', True),
    (re.compile(r'^卷首$'), 'juanshou', False),
    (re.compile(r'^卷末(\d+)$'), 'juanmo', True),
    (re.compile(r'^卷末$'), 'juanmo', False),
    (re.compile(r'^附錄(\d+)$'), 'fulu', True),
    (re.compile(r'^附錄$'), 'fulu', False),
    (re.compile(r'^附录(\d+)$'), 'fulu', True),
    (re.compile(r'^附录$'), 'fulu', False),
    (re.compile(r'^序(\d+)$'), 'xu', True),
    (re.compile(r'^序$'), 'xu', False),
    (re.compile(r'^跋(\d+)$'), 'ba', True),
    (re.compile(r'^跋$'), 'ba', False),
    (re.compile(r'^目錄(\d+)$'), 'mulu', True),
    (re.compile(r'^目錄$'), 'mulu', False),
    (re.compile(r'^目录(\d+)$'), 'mulu', True),
    (re.compile(r'^目录$'), 'mulu', False),
    (re.compile(r'^凡例(\d+)$'), 'fanli', True),
    (re.compile(r'^凡例$'), 'fanli', False),
    (re.compile(r'^總目(\d+)$'), 'zongmu', True),
    (re.compile(r'^總目$'), 'zongmu', False),
    (re.compile(r'^总目(\d+)$'), 'zongmu', True),
    (re.compile(r'^总目$'), 'zongmu', False),
]


def _title_to_filename(title: str, juan_index: int, juan_total: int) -> str:
    """Convert a chapter title to a filename.

    Special titles (卷首, 附錄, etc.) get pinyin-based names.
    Regular titles (卷001, 卷一, etc.) get sequential juan{NNN} names.
    """
    for pattern, prefix, has_num in _SPECIAL_JUAN_PATTERNS:
        m = pattern.match(title)
        if m:
            if has_num:
                return f"{prefix}{m.group(1)}.json"
            else:
                return f"{prefix}.json"

    # Default: sequential juan numbering
    width = max(2, len(str(juan_total))) if juan_total else 2
    return f"juan{juan_index:0{width}d}.json"


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
    supports_search = True

    API_URL = "https://zh.wikisource.org/w/api.php"

    default_headers = {
        "Accept": "application/json",
        "User-Agent": "GujiPlatform/1.0 (https://github.com/open-guji; guji@example.com)",
    }

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    def get_headers(self, url: str = None) -> dict:
        """Override to always use Wikisource-compliant User-Agent.

        MediaWiki API requires a descriptive UA with contact info;
        generic browser UAs get 403 Forbidden.
        """
        headers = dict(self.default_headers)
        return headers

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
        pending_leaves: list[tuple[ManifestNode, str]] = []  # (node, title) for filename generation
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
                pending_leaves.append((node, parts[0]))
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
                pending_leaves.append((leaf, parts[-1]))

            if progress_callback:
                progress_callback("chapter", full_title)

        # Generate filenames for each leaf node.
        # Special titles (卷首, 附錄, etc.) get pinyin names;
        # regular chapters get sequential juan{NNN} names.
        for leaf_node, leaf_title in pending_leaves:
            leaf_node.source_data["juan_total"] = chapter_seq
            leaf_node.source_data["filename"] = _title_to_filename(
                leaf_title, leaf_node.source_data["juan_index"], chapter_seq,
            )

        for node in section_nodes.values():
            node.children_count = len(node.children)

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Wikisource is text-only, no images."""
        return []

    async def get_structured_text(self, book_id: str, index_id: str = "", progress_callback=None) -> Optional[StructuredText]:
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

        # Use pre-computed filename from discover_structure, or fallback
        filename = node.source_data.get("filename")
        if not filename:
            juan_index = node.source_data.get("juan_index")
            if juan_index:
                total = node.source_data.get("juan_total", 0)
                filename = _title_to_filename(
                    node.title, juan_index, total)
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

    # ------------------------------------------------------------------
    # Search (supports_search = True)
    # ------------------------------------------------------------------

    # CJK variant pairs commonly seen in classical Chinese book titles.
    # Used to expand search queries so that e.g. "注" also matches "註".
    _CJK_VARIANTS: dict[str, str] = {
        '注': '註', '註': '注',
        '于': '於', '於': '于',
        '台': '臺', '臺': '台',
        '里': '裏', '裏': '里',
        '群': '羣', '羣': '群',
        '峰': '峯', '峯': '峰',
        '叙': '敘', '敘': '叙',
        '踪': '蹤', '蹤': '踪',
        '线': '綫', '綫': '线',
        '并': '並', '並': '并',
        '灾': '災', '災': '灾',
        '余': '餘', '餘': '余',
        # Additional pairs for match_book (from JS script)
        '萬': '万', '万': '萬',
        '與': '与', '与': '與',
        '書': '书', '书': '書',
        '經': '经', '经': '經',
        '傳': '传', '传': '傳',
        '記': '记', '记': '記',
        '說': '说', '说': '說',
        '學': '学', '学': '學',
        '義': '义', '义': '義',
        '國': '国', '国': '國',
        '圖': '图', '图': '圖',
        '爲': '為', '為': '爲',
        '觀': '观', '观': '觀',
        '詩': '诗', '诗': '詩',
        '禮': '礼', '礼': '禮',
        '論': '论', '论': '論',
        '續': '续', '续': '續',
        '補': '补', '补': '補',
        '訂': '订', '订': '訂',
        '鑑': '鉴', '鉴': '鑑',
        '類': '类', '类': '類',
        '彙': '汇', '汇': '彙',
        '歷': '历', '历': '歷',
        '筆': '笔', '笔': '筆',
    }

    # Version suffix pattern: "书名 (四庫全書本)" or "书名（通志堂本）"
    _VERSION_SUFFIX_RE = re.compile(r'^(.+?)\s*[（(](.+?)[）)]$')

    # Known version suffixes on Wikisource
    _VERSION_SUFFIXES: list[str] = [
        '四庫全書本', '四部叢刊本', '四部備要本',
        '百衲本', '武英殿本', '摛藻堂四庫全書薈要本',
    ]

    # Removable title prefixes (e.g. 欽定四庫全書 → 四庫全書)
    _REMOVABLE_PREFIXES: list[str] = ['欽定', '御定', '御纂', '御製', '御選']

    # Version suffix slug mapping (Chinese → short English ID)
    _SLUG_MAP: dict[str, str] = {
        '四庫全書本': 'siku',
        '四部叢刊本': 'sibu-congkan',
        '四部備要本': 'sibu-beiyao',
        '百衲本': 'baina',
        '武英殿本': 'wuyingdian',
        '摛藻堂四庫全書薈要本': 'huiyao',
    }

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search Wikisource for books matching *query*.

        Handles CJK variant expansion, disambiguation detection,
        and multi-version grouping automatically.
        """
        # 1. Search with variant expansion
        queries = self._expand_variants(query)
        raw_results = await self._mediawiki_search(queries[0], limit, offset)
        seen_ids = {r["pageid"] for r in raw_results}
        total_hits = raw_results[0]["_total"] if raw_results else 0

        # If we have a variant query, merge results
        if len(queries) > 1:
            for vq in queries[1:]:
                extra = await self._mediawiki_search(vq, limit, 0)
                for r in extra:
                    if r["pageid"] not in seen_ids:
                        raw_results.append(r)
                        seen_ids.add(r["pageid"])
                if extra and extra[0].get("_total", 0) > total_hits:
                    total_hits = extra[0]["_total"]

        if not raw_results:
            return SearchResponse(query=query, total_hits=0)

        # 2. Build SearchResult objects
        results = [
            SearchResult(
                title=r["title"],
                page_id=r["pageid"],
                url=f"https://zh.wikisource.org/wiki/{r['title']}",
                snippet=self._clean_snippet(r.get("snippet", "")),
                source_site=self.site_id,
            )
            for r in raw_results
        ]

        # 3. Batch-detect disambiguation pages
        await self._detect_disambiguation_batch(results)

        # 4. Expand disambiguation pages
        for r in results:
            if r.is_disambiguation:
                r.versions = await self._expand_disambiguation(r.title)

        # 5. Group multi-version results
        results = self._group_versions(results)

        has_more = offset + len(results) < total_hits
        continuation = str(offset + limit) if has_more else ""

        return SearchResponse(
            query=query,
            results=results,
            total_hits=total_hits,
            has_more=has_more,
            continuation=continuation,
        )

    def _expand_variants(self, query: str) -> list[str]:
        """Generate variant queries for CJK character differences.

        For short queries (≤ 10 chars), produce one extra variant per
        distinct mapping found.  For longer queries, rely on MediaWiki's
        built-in variant handling.
        """
        if len(query) > 10:
            return [query]

        variant_chars: dict[int, str] = {}
        for i, ch in enumerate(query):
            if ch in self._CJK_VARIANTS:
                variant_chars[i] = self._CJK_VARIANTS[ch]

        if not variant_chars:
            return [query]

        # Build a single variant with all substitutions applied
        chars = list(query)
        for i, alt in variant_chars.items():
            chars[i] = alt
        variant = "".join(chars)

        return [query, variant]

    async def _mediawiki_search(
        self, query: str, limit: int, offset: int,
    ) -> list[dict]:
        """Call MediaWiki search API and return raw result dicts.

        Each dict has keys: title, pageid, snippet, plus a private
        _total key with the total hit count.
        """
        session = await self.get_session()
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(min(limit, 50)),
            "sroffset": str(offset),
            "format": "json",
        }

        try:
            async with session.get(self.API_URL, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()

                total = data.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
                items = data.get("query", {}).get("search", [])
                for item in items:
                    item["_total"] = total
                return items
        except Exception as e:
            logger.warning(f"Wikisource search failed for '{query}': {e}")
            return []

    async def _detect_disambiguation_batch(
        self, results: list[SearchResult],
    ) -> None:
        """Batch-fetch categories and mark disambiguation pages."""
        if not results:
            return

        session = await self.get_session()
        batch_size = 50

        for i in range(0, len(results), batch_size):
            batch = results[i:i + batch_size]
            titles = "|".join(r.title for r in batch)

            params = {
                "action": "query",
                "titles": titles,
                "prop": "categories",
                "cllimit": "50",
                "format": "json",
            }

            try:
                async with session.get(self.API_URL, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

                    pages = data.get("query", {}).get("pages", {})
                    # Build title → categories lookup
                    cat_map: dict[str, list[str]] = {}
                    for page_data in pages.values():
                        title = page_data.get("title", "")
                        cats = [
                            c.get("title", "").replace("Category:", "")
                            for c in page_data.get("categories", [])
                        ]
                        cat_map[title] = cats

                    for r in batch:
                        cats = cat_map.get(r.title, [])
                        r.categories = cats
                        if "消歧義" in cats or "消歧义" in cats:
                            r.is_disambiguation = True

            except Exception as e:
                logger.warning(f"Failed to fetch categories: {e}")

    async def _expand_disambiguation(self, title: str) -> list[SearchResult]:
        """Fetch a disambiguation page's wikitext and extract linked titles."""
        wikitext = await self._fetch_wikitext(title)
        if not wikitext:
            return []

        # Extract wiki links: [[Target|Display]] or [[Target]]
        link_re = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')
        results = []

        for m in link_re.finditer(wikitext):
            target = m.group(1).strip()
            # Skip non-article links
            if any(target.startswith(p) for p in (
                "Category:", "分類:", "Author:", "作者:",
                "Wikisource:", "Special:", "s:", "w:",
            )):
                continue
            results.append(SearchResult(
                title=target,
                url=f"https://zh.wikisource.org/wiki/{target}",
                source_site=self.site_id,
            ))

        return results

    def _group_versions(
        self, results: list[SearchResult],
    ) -> list[SearchResult]:
        """Group results with version suffixes under a single entry.

        E.g. "周易鄭康成註", "周易鄭康成註 (四庫全書本)",
        "周易鄭康成注 (四部叢刊本)" → one result with 3 versions.
        """
        # Pass 1: identify base names and version suffixes
        base_map: dict[str, list[SearchResult]] = {}
        standalone: list[SearchResult] = []

        for r in results:
            # Skip disambiguation pages — they already have their own versions
            if r.is_disambiguation:
                standalone.append(r)
                continue

            m = self._VERSION_SUFFIX_RE.match(r.title)
            if m:
                base_name = m.group(1).strip()
                # Normalize variant characters in base name for grouping
                norm = self._normalize_variants(base_name)
                base_map.setdefault(norm, []).append(r)
            else:
                # Could be a base entry itself
                norm = self._normalize_variants(r.title)
                base_map.setdefault(norm, []).append(r)

        # Pass 2: merge groups
        grouped: list[SearchResult] = []
        seen_norms: set[str] = set()

        for r in results:
            if r.is_disambiguation:
                grouped.append(r)
                continue

            m = self._VERSION_SUFFIX_RE.match(r.title)
            base = m.group(1).strip() if m else r.title
            norm = self._normalize_variants(base)

            if norm in seen_norms:
                continue
            seen_norms.add(norm)

            group = base_map.get(norm, [r])
            if len(group) >= 2:
                # Find the "main" entry (one without version suffix)
                main = next(
                    (x for x in group if not self._VERSION_SUFFIX_RE.match(x.title)),
                    group[0],
                )
                main.versions = [x for x in group if x is not main]
                grouped.append(main)
            else:
                grouped.append(group[0])

        return grouped

    def _normalize_variants(self, text: str) -> str:
        """Normalize CJK variants to a canonical form for grouping."""
        chars = []
        for ch in text:
            # Always map to the "first" variant (alphabetically)
            alt = self._CJK_VARIANTS.get(ch)
            if alt and alt < ch:
                chars.append(alt)
            else:
                chars.append(ch)
        return "".join(chars)

    @staticmethod
    def _clean_snippet(snippet: str) -> str:
        """Remove HTML tags from MediaWiki search snippet."""
        return re.sub(r'<[^>]+>', '', snippet)

    # ------------------------------------------------------------------
    # match_book — exact title + author matching for book index
    # ------------------------------------------------------------------

    async def match_book(
        self,
        title: str,
        authors: list[str] | None = None,
        delay: float = 1.0,
    ) -> list[MatchedResource]:
        """Match a book by exact title + author against Wikisource.

        Strategy:
        1. Generate CJK variant titles + removable-prefix variants
        2. Probe exact title + version-suffix combinations via API
        3. Handle disambiguation pages using author names
        4. Fallback: intitle: search with author filtering

        Args:
            title: Book title (e.g. "周易鄭康成註")
            authors: Author names for disambiguation (e.g. ["鄭玄"])
            delay: Seconds between API requests (rate-limiting)

        Returns:
            List of matched resources (may be empty).
        """
        authors = authors or []
        found: list[MatchedResource] = []
        seen_urls: set[str] = set()

        def add_result(res_id: str, name: str, url: str, details: str = ""):
            if url in seen_urls:
                return
            seen_urls.add(url)
            found.append(MatchedResource(
                id=res_id, name=name, url=url, details=details,
            ))

        # Step 1: generate title variants
        title_variants = self._generate_title_variants(title)

        # Add version-suffix variants
        all_titles = list(title_variants)
        for suffix in self._VERSION_SUFFIXES:
            for v in title_variants:
                all_titles.append(f"{v} ({suffix})")

        # Step 2: batch check page existence + disambiguation
        page_info = await self._check_pages_batch(all_titles)
        await asyncio.sleep(delay)

        # Step 3: process results
        for page_title, info in page_info.items():
            if not info["exists"]:
                continue

            if info["is_disambig"]:
                links = await self._extract_disambig_links(page_title)
                await asyncio.sleep(delay)

                for link in links:
                    link_title = link["title"]
                    # Strategy A: author name appears in link title
                    matches_author = (
                        len(authors) > 0
                        and any(a in link_title for a in authors)
                    )
                    # Strategy B: link is a plain main entry (no parenthetical)
                    link_base = re.sub(
                        r'\s*[（(][^）)]+[）)]\s*$', '', link_title,
                    )
                    is_main_entry = (
                        link_title == link_base
                        and any(
                            link_base in self._generate_title_variants(v)
                            for v in title_variants
                        )
                    )

                    if matches_author or is_main_entry:
                        suffix = self._extract_version_suffix(link_title)
                        res_id = f"wikisource-{self._slugify(suffix)}" if suffix else "wikisource"
                        res_name = f"维基文库（{suffix}）" if suffix else "维基文库"
                        add_result(res_id, res_name, link["url"])
            else:
                suffix = self._extract_version_suffix(page_title)
                res_id = f"wikisource-{self._slugify(suffix)}" if suffix else "wikisource"
                res_name = f"维基文库（{suffix}）" if suffix else "维基文库"
                add_result(res_id, res_name, self._wiki_url(page_title))

        # Step 4: fallback intitle: search if nothing found
        if not found:
            search_results = await self._intitle_search(title)
            await asyncio.sleep(delay)

            candidates = []
            for sr in search_results:
                if "/" in sr["title"]:
                    continue
                variant_match = any(
                    sr["title"] == v or sr["title"].startswith(v + " (")
                    for v in title_variants
                )
                if not variant_match:
                    continue
                suffix = self._extract_version_suffix(sr["title"])
                if suffix and suffix not in self._VERSION_SUFFIXES:
                    if not (authors and any(a in suffix for a in authors)):
                        continue
                candidates.append(sr["title"])

            if candidates:
                candidate_info = await self._check_pages_batch(candidates)
                await asyncio.sleep(delay)

                for ct, ci in candidate_info.items():
                    if ci["is_disambig"]:
                        continue
                    suffix = self._extract_version_suffix(ct)
                    res_id = f"wikisource-{self._slugify(suffix)}" if suffix else "wikisource"
                    res_name = f"维基文库（{suffix}）" if suffix else "维基文库"
                    add_result(res_id, res_name, self._wiki_url(ct))

        return found

    # -- match_book helpers --

    def _generate_title_variants(self, title: str) -> list[str]:
        """Generate CJK variant titles (single-char substitutions + prefix removal)."""
        variants: set[str] = {title}

        # Single-char variant substitutions
        for i, ch in enumerate(title):
            alt = self._CJK_VARIANTS.get(ch)
            if alt:
                variants.add(title[:i] + alt + title[i + 1:])

        # Removable prefixes
        for prefix in self._REMOVABLE_PREFIXES:
            if title.startswith(prefix):
                stripped = title[len(prefix):]
                variants.add(stripped)
                for i, ch in enumerate(stripped):
                    alt = self._CJK_VARIANTS.get(ch)
                    if alt:
                        variants.add(stripped[:i] + alt + stripped[i + 1:])

        return list(variants)

    async def _check_pages_batch(
        self, titles: list[str],
    ) -> dict[str, dict]:
        """Batch-check page existence + disambiguation, with redirect resolution.

        Returns: {canonical_title: {"exists": bool, "pageid": int, "is_disambig": bool}}
        """
        results: dict[str, dict] = {}
        session = await self.get_session()
        batch_size = 50

        for i in range(0, len(titles), batch_size):
            batch = titles[i:i + batch_size]
            params = {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "categories",
                "clcategories": "Category:消歧义|Category:消歧義",
                "redirects": "1",
                "formatversion": "2",
                "format": "json",
            }

            try:
                async with session.get(self.API_URL, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

                    for p in data.get("query", {}).get("pages", []):
                        if p.get("missing"):
                            continue
                        canonical = p["title"]
                        if canonical in results:
                            continue
                        results[canonical] = {
                            "exists": True,
                            "pageid": p.get("pageid", 0),
                            "is_disambig": bool(p.get("categories")),
                        }
            except Exception as e:
                logger.warning(f"_check_pages_batch failed: {e}")

        return results

    async def _extract_disambig_links(self, title: str) -> list[dict]:
        """Extract wiki links from a disambiguation page.

        Returns: [{"title": str, "url": str}]
        """
        wikitext = await self._fetch_wikitext(title)
        if not wikitext:
            return []

        link_re = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')
        links = []
        for m in link_re.finditer(wikitext):
            target = m.group(1).strip()
            if re.match(
                r'^(Category|分類|Author|作者|Wikisource|Special|'
                r's|w|Wikipedia|Commons|File|Image):',
                target, re.IGNORECASE,
            ):
                continue
            if target.startswith('#'):
                continue
            links.append({
                "title": target,
                "url": self._wiki_url(target),
            })
        return links

    async def _intitle_search(self, title: str) -> list[dict]:
        """Fallback search using intitle: query.

        Returns: [{"title": str, "pageid": int, "url": str}]
        """
        session = await self.get_session()
        params = {
            "action": "query",
            "list": "search",
            "srsearch": f'intitle:"{title}"',
            "srlimit": "20",
            "srnamespace": "0",
            "formatversion": "2",
            "format": "json",
        }

        try:
            async with session.get(self.API_URL, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return [
                    {
                        "title": r["title"],
                        "pageid": r["pageid"],
                        "url": self._wiki_url(r["title"]),
                    }
                    for r in data.get("query", {}).get("search", [])
                ]
        except Exception as e:
            logger.warning(f"_intitle_search failed for '{title}': {e}")
            return []

    @staticmethod
    def _extract_version_suffix(title: str) -> str:
        """Extract parenthetical suffix: '周易 (四庫全書本)' → '四庫全書本'."""
        m = re.search(r'[（(]([^）)]+)[）)]\s*$', title)
        return m.group(1) if m else ""

    def _slugify(self, text: str) -> str:
        """Map Chinese version name to short English slug."""
        return self._SLUG_MAP.get(text, text.replace(' ', '-').lower())

    @staticmethod
    def _wiki_url(page_title: str) -> str:
        """Build a human-readable Wikisource URL (no percent-encoding for CJK)."""
        return "https://zh.wikisource.org/wiki/" + page_title.replace(' ', '_')

    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
