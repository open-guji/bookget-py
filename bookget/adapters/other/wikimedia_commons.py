# 维基共享资源 (Wikimedia Commons) Adapter
# https://commons.wikimedia.org/

import re
from typing import List, Optional
from urllib.parse import unquote, quote
import aiohttp
import asyncio

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...models.search import SearchResult, SearchResponse, MatchedResource
from ...text_parsers.base import StructuredText
from ...logger import logger
from ...exceptions import MetadataExtractionError, DownloadError


# CJK 字符变体映射（简繁等常见替换）
_CJK_VARIANTS: dict[str, str] = {
    '注': '註', '註': '注',
    '于': '於', '於': '于',
    '余': '餘', '餘': '余',
    '云': '雲', '雲': '云',
    '丰': '豐', '豐': '丰',
    '后': '後', '後': '后',
    '志': '誌', '誌': '志',
    '谷': '穀', '穀': '谷',
    '历': '歷', '歷': '历',
    '钟': '鐘', '鐘': '钟',
    '制': '製', '製': '制',
    '面': '麵', '麵': '面',
}


@AdapterRegistry.register
class WikimediaCommonsAdapter(BaseSiteAdapter):
    """
    Adapter for 维基共享资源 (Wikimedia Commons).

    Wikimedia Commons hosts free media files including scanned books
    (DjVu/PDF), high-resolution artifact images, and historical photographs.

    URL patterns:
    - File page:     https://commons.wikimedia.org/wiki/File:Book.djvu
    - Category page: https://commons.wikimedia.org/wiki/Category:Chinese_classics
    - Alt URL:       https://commons.wikimedia.org/w/index.php?title=File:Book.djvu
    """

    site_name = "维基共享资源"
    site_id = "wikimedia_commons"
    site_domains = ["commons.wikimedia.org"]

    supports_iiif = False
    supports_images = True
    supports_text = False
    supports_search = True

    API_URL = "https://commons.wikimedia.org/w/api.php"

    default_headers = {
        "Accept": "application/json",
        "User-Agent": "GujiPlatform/1.0 (https://github.com/open-guji; guji@example.com)",
    }

    # ------------------------------------------------------------------
    # HTTP session management
    # ------------------------------------------------------------------

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.default_headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # extract_book_id
    # ------------------------------------------------------------------

    def extract_book_id(self, url: str) -> str:
        """Extract File: or Category: identifier from a Commons URL."""
        # /wiki/File:... or /wiki/Category:...
        m = re.search(r'/wiki/((?:File|Category):[^\s?#]+)', url)
        if m:
            return unquote(m.group(1)).replace('_', ' ')

        # /w/index.php?title=File:...
        m = re.search(r'[?&]title=((?:File|Category):[^\s&#]+)', url)
        if m:
            return unquote(m.group(1)).replace('_', ' ')

        raise MetadataExtractionError(
            f"无法从 URL 提取 File: 或 Category: 标识符: {url}"
        )

    def _is_category(self, book_id: str) -> bool:
        return book_id.startswith("Category:")

    @staticmethod
    def _wiki_url(page_title: str) -> str:
        """Build a Commons URL for a page title."""
        return "https://commons.wikimedia.org/wiki/" + page_title.replace(' ', '_')

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from a string."""
        return re.sub(r'<[^>]+>', '', text).strip()

    # ------------------------------------------------------------------
    # get_metadata
    # ------------------------------------------------------------------

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Fetch metadata for a File or Category page."""
        meta = BookMetadata(
            source_id=book_id,
            source_url=self._wiki_url(book_id),
            source_site=self.site_id,
        )

        if self._is_category(book_id):
            return await self._get_category_metadata(book_id, meta)
        else:
            return await self._get_file_metadata(book_id, meta)

    async def _get_file_metadata(self, book_id: str, meta: BookMetadata) -> BookMetadata:
        """Fetch metadata for a File: page via imageinfo API."""
        session = await self.get_session()
        params = {
            "action": "query",
            "titles": book_id,
            "prop": "imageinfo",
            "iiprop": "url|size|mime|mediatype|extmetadata|pagecount",
            "iiurlwidth": "2000",
            "formatversion": "2",
            "format": "json",
        }

        async with session.get(self.API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            raise MetadataExtractionError(f"文件不存在: {book_id}")

        page = pages[0]
        info = page.get("imageinfo", [{}])[0]
        ext = info.get("extmetadata", {})

        # Map extmetadata fields
        meta.title = self._strip_html(
            ext.get("ObjectName", {}).get("value", "")
        ) or book_id.removeprefix("File:").rsplit(".", 1)[0]

        artist = self._strip_html(ext.get("Artist", {}).get("value", ""))
        if artist:
            meta.creators = [Creator(name=artist)]

        meta.date = self._strip_html(
            ext.get("DateTimeOriginal", {}).get("value", "")
            or ext.get("DateTime", {}).get("value", "")
        )

        meta.license = self._strip_html(
            ext.get("LicenseShortName", {}).get("value", "")
        )

        description = self._strip_html(
            ext.get("ImageDescription", {}).get("value", "")
        )

        meta.raw_metadata = {
            "mime": info.get("mime", ""),
            "pagecount": info.get("pagecount", 1),
            "original_url": info.get("url", ""),
            "thumburl": info.get("thumburl", ""),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "size": info.get("size", 0),
            "description": description,
        }
        meta.pages = info.get("pagecount", 1)

        return meta

    async def _get_category_metadata(self, book_id: str, meta: BookMetadata) -> BookMetadata:
        """Fetch metadata for a Category: page."""
        session = await self.get_session()
        params = {
            "action": "query",
            "titles": book_id,
            "prop": "categoryinfo",
            "formatversion": "2",
            "format": "json",
        }

        async with session.get(self.API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            raise MetadataExtractionError(f"分类不存在: {book_id}")

        page = pages[0]
        cat_info = page.get("categoryinfo", {})

        meta.title = book_id.removeprefix("Category:").replace('_', ' ')
        meta.pages = cat_info.get("files", 0)
        meta.raw_metadata = {
            "total_files": cat_info.get("files", 0),
            "total_subcats": cat_info.get("subcats", 0),
            "total_pages": cat_info.get("pages", 0),
        }

        return meta

    # ------------------------------------------------------------------
    # get_image_list
    # ------------------------------------------------------------------

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Get list of downloadable image resources."""
        if self._is_category(book_id):
            return await self._get_category_files(book_id)
        else:
            return await self._get_file_pages(book_id)

    async def _get_file_pages(self, book_id: str) -> List[Resource]:
        """Generate Resource list for a single file (may be multi-page DjVu/PDF)."""
        meta = await self._get_file_metadata(book_id, BookMetadata())
        raw = meta.raw_metadata
        pagecount = raw.get("pagecount", 1)
        mime = raw.get("mime", "")
        original_url = raw.get("original_url", "")
        thumburl = raw.get("thumburl", "")

        # Single image file (not DjVu/PDF)
        is_multipage = (
            pagecount > 1
            or "djvu" in mime.lower()
            or "pdf" in mime.lower()
        )

        if not is_multipage:
            ext = self._get_extension(mime, book_id)
            return [Resource(
                url=original_url,
                resource_type=ResourceType.IMAGE,
                order=1,
                filename=f"0001{ext}",
            )]

        # Multi-page document: generate thumb URLs for each page
        if not thumburl:
            # Fallback: fetch thumburl for page 1
            thumburl = await self._fetch_thumb_url(book_id, page=1)

        if not thumburl:
            raise DownloadError(f"无法获取缩略图 URL: {book_id}")

        resources = []
        for page_num in range(1, pagecount + 1):
            page_url = re.sub(r'page\d+-', f'page{page_num}-', thumburl)
            resources.append(Resource(
                url=page_url,
                resource_type=ResourceType.IMAGE,
                order=page_num,
                page=str(page_num),
                filename=f"{page_num:04d}.jpg",
            ))

        return resources

    async def _fetch_thumb_url(self, book_id: str, page: int = 1) -> str:
        """Fetch the thumb URL for a specific page of a multi-page document."""
        session = await self.get_session()
        params = {
            "action": "query",
            "titles": book_id,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": "2000",
            "iiurlparam": f"page{page}-2000px",
            "formatversion": "2",
            "format": "json",
        }

        async with session.get(self.API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return ""
        info = pages[0].get("imageinfo", [{}])[0]
        return info.get("thumburl", "")

    async def _get_category_files(self, book_id: str) -> List[Resource]:
        """List all files in a category and generate Resource list."""
        session = await self.get_session()
        file_titles: List[str] = []
        cmcontinue = ""

        # Paginate through category members
        while True:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": book_id,
                "cmtype": "file",
                "cmlimit": "500",
                "cmprop": "title",
                "formatversion": "2",
                "format": "json",
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue

            async with session.get(self.API_URL, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()

            members = data.get("query", {}).get("categorymembers", [])
            file_titles.extend(m["title"] for m in members)

            cont = data.get("continue", {}).get("cmcontinue")
            if not cont:
                break
            cmcontinue = cont

        if not file_titles:
            return []

        # Batch fetch original URLs for all files
        file_urls = await self._get_file_urls_batch(file_titles)

        resources = []
        for i, title in enumerate(file_titles, 1):
            url = file_urls.get(title, "")
            if not url:
                continue
            # Use original filename from title
            fname = title.removeprefix("File:").replace(' ', '_')
            resources.append(Resource(
                url=url,
                resource_type=ResourceType.IMAGE,
                order=i,
                filename=fname,
            ))

        return resources

    async def _get_file_urls_batch(self, titles: List[str]) -> dict[str, str]:
        """Batch fetch original file URLs via imageinfo API (50 per batch)."""
        session = await self.get_session()
        result: dict[str, str] = {}
        batch_size = 50

        for i in range(0, len(titles), batch_size):
            batch = titles[i:i + batch_size]
            params = {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "imageinfo",
                "iiprop": "url",
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
                    info = p.get("imageinfo", [{}])[0]
                    result[p["title"]] = info.get("url", "")
            except Exception as e:
                logger.warning(f"_get_file_urls_batch failed: {e}")

        return result

    @staticmethod
    def _get_extension(mime: str, fallback_name: str = "") -> str:
        """Determine file extension from MIME type."""
        mime_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/tiff": ".tif",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/vnd.djvu": ".djvu",
            "application/pdf": ".pdf",
        }
        ext = mime_map.get(mime.lower(), "")
        if not ext and fallback_name:
            m = re.search(r'\.(\w+)$', fallback_name)
            if m:
                ext = f".{m.group(1).lower()}"
        return ext or ".jpg"

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search for files on Wikimedia Commons (File namespace)."""
        session = await self.get_session()
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srnamespace": "6",
            "srlimit": str(min(limit, 50)),
            "sroffset": str(offset),
            "formatversion": "2",
            "format": "json",
        }

        async with session.get(self.API_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        search_data = data.get("query", {}).get("search", [])
        total = data.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
        continuation = data.get("continue", {}).get("sroffset", "")

        results = []
        for item in search_data:
            title = item.get("title", "")
            results.append(SearchResult(
                title=title,
                page_id=item.get("pageid", 0),
                url=self._wiki_url(title),
                snippet=self._strip_html(item.get("snippet", "")),
                source_site=self.site_id,
            ))

        return SearchResponse(
            query=query,
            results=results,
            total_hits=total,
            has_more=bool(continuation),
            continuation=str(continuation),
        )

    # ------------------------------------------------------------------
    # match_book — exact title + author matching
    # ------------------------------------------------------------------

    async def match_book(
        self,
        title: str,
        authors: list[str] | None = None,
        delay: float = 1.0,
    ) -> list[MatchedResource]:
        """Match a book by exact title + author against Wikimedia Commons.

        Strategy:
        1. Generate title variants (CJK character substitutions)
        2. Search File namespace for DjVu/PDF files matching title
        3. Filter results by title relevance and author (if provided)
        4. Return matched resources with download URLs

        Args:
            title: Book title (e.g. "周易" or "Dream of the Red Chamber")
            authors: Author names for filtering
            delay: Seconds between API requests (rate-limiting)

        Returns:
            List of matched resources (may be empty).
        """
        authors = authors or []
        found: list[MatchedResource] = []
        seen_urls: set[str] = set()

        def add_result(url: str, name: str, details: str = ""):
            if url in seen_urls:
                return
            seen_urls.add(url)
            found.append(MatchedResource(
                id="wikimedia_commons",
                name=name,
                url=url,
                type="image",
                details=details,
            ))

        # Step 1: generate title variants
        title_variants = self._generate_title_variants(title)

        # Step 2: search for matching files (DjVu + PDF)
        search_queries = []
        for v in title_variants:
            search_queries.append(f'intitle:"{v}"')

        # Deduplicate queries
        search_queries = list(dict.fromkeys(search_queries))

        all_candidates: list[dict] = []
        for q in search_queries:
            results = await self._search_files(q, limit=20)
            all_candidates.extend(results)
            await asyncio.sleep(delay)

        if not all_candidates:
            return found

        # Deduplicate by title
        seen_titles: set[str] = set()
        unique_candidates: list[dict] = []
        for c in all_candidates:
            if c["title"] not in seen_titles:
                seen_titles.add(c["title"])
                unique_candidates.append(c)

        # Step 3: filter by title relevance
        relevant: list[dict] = []
        for c in unique_candidates:
            file_name = c["title"].removeprefix("File:").rsplit(".", 1)[0]
            # Normalize: replace underscores and common separators
            file_name_norm = file_name.replace('_', ' ').replace('-', ' ')
            if any(v in file_name_norm for v in title_variants):
                relevant.append(c)

        if not relevant:
            # Relaxed matching: check if any variant is a substring
            for c in unique_candidates:
                file_name = c["title"].removeprefix("File:")
                file_name_lower = file_name.lower().replace('_', ' ')
                if any(v.lower() in file_name_lower for v in title_variants):
                    relevant.append(c)

        if not relevant:
            return found

        # Step 4: if authors provided, fetch extmetadata for filtering
        if authors:
            titles_to_check = [c["title"] for c in relevant]
            ext_batch = await self._get_file_extmetadata_batch(titles_to_check)
            await asyncio.sleep(delay)

            for c in relevant:
                ext = ext_batch.get(c["title"], {})
                if self._author_matches(ext, authors):
                    file_title = c["title"]
                    display_name = file_title.removeprefix("File:").rsplit(".", 1)[0].replace('_', ' ')
                    add_result(
                        self._wiki_url(file_title),
                        f"维基共享资源",
                        details=display_name,
                    )
        else:
            for c in relevant:
                file_title = c["title"]
                display_name = file_title.removeprefix("File:").rsplit(".", 1)[0].replace('_', ' ')
                add_result(
                    self._wiki_url(file_title),
                    f"维基共享资源",
                    details=display_name,
                )

        return found

    # -- match_book helpers --

    def _generate_title_variants(self, title: str) -> list[str]:
        """Generate CJK variant titles (single-char substitutions)."""
        variants: set[str] = {title}

        # Single-char variant substitutions
        for i, ch in enumerate(title):
            alt = _CJK_VARIANTS.get(ch)
            if alt:
                variants.add(title[:i] + alt + title[i + 1:])

        return list(variants)

    async def _search_files(self, query: str, limit: int = 20) -> list[dict]:
        """Search File namespace on Commons.

        Returns: [{"title": str, "pageid": int}]
        """
        session = await self.get_session()
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srnamespace": "6",
            "srlimit": str(min(limit, 50)),
            "formatversion": "2",
            "format": "json",
        }

        try:
            async with session.get(self.API_URL, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return [
                    {"title": r["title"], "pageid": r["pageid"]}
                    for r in data.get("query", {}).get("search", [])
                ]
        except Exception as e:
            logger.warning(f"_search_files failed for '{query}': {e}")
            return []

    async def _get_file_extmetadata_batch(
        self, titles: list[str],
    ) -> dict[str, dict]:
        """Batch fetch extmetadata for files (50 per batch).

        Returns: {title: {field: value, ...}}
        """
        session = await self.get_session()
        result: dict[str, dict] = {}
        batch_size = 50

        for i in range(0, len(titles), batch_size):
            batch = titles[i:i + batch_size]
            params = {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "imageinfo",
                "iiprop": "extmetadata",
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
                    info = p.get("imageinfo", [{}])[0]
                    ext = info.get("extmetadata", {})
                    result[p["title"]] = {
                        k: self._strip_html(v.get("value", ""))
                        for k, v in ext.items()
                    }
            except Exception as e:
                logger.warning(f"_get_file_extmetadata_batch failed: {e}")

        return result

    @staticmethod
    def _author_matches(extmetadata: dict, authors: list[str]) -> bool:
        """Check if any author name appears in file metadata."""
        if not authors or not extmetadata:
            return not authors  # No authors = match all

        # Check Artist, ImageDescription, ObjectName fields
        searchable = " ".join([
            extmetadata.get("Artist", ""),
            extmetadata.get("ImageDescription", ""),
            extmetadata.get("ObjectName", ""),
            extmetadata.get("Credit", ""),
        ])

        return any(author in searchable for author in authors)
