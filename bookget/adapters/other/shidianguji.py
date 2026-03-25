# 识典古籍 (Shidianguji) Adapter
# https://www.shidianguji.com/
#
# Uses Playwright browser automation to bypass ByteDance SecSDK anti-bot protection.
# SecSDK generates device fingerprints (verifyFp / a_bogus) required for all API calls.

import re
import asyncio
import json
import urllib.parse
from typing import List, Optional, Callable

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...models.search import MatchedResource, SearchResponse, SearchResult
from ...text_parsers.base import StructuredText
from ...text_parsers.shidianguji_parser import ShidianGujiParser
from ...logger import logger
from ...exceptions import MetadataExtractionError, DownloadError

try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@AdapterRegistry.register
class ShidianGujiAdapter(BaseSiteAdapter):
    """
    Adapter for 识典古籍 (shidianguji.com).

    Requires Playwright for browser automation (ByteDance SecSDK auth).
    Install: pip install playwright && playwright install chromium

    Supports:
    - Image download: captures signed CDN URLs by navigating the reader
    - Text download: intercepts unencrypted paragraphs API responses

    URL patterns:
    - Book: https://www.shidianguji.com/zh/book/{book_id}
    - Book: https://www.shidianguji.com/book/{book_id}
    """

    site_name = "识典古籍"
    site_id = "shidianguji"
    site_domains = ["shidianguji.com", "www.shidianguji.com"]

    supports_iiif = False
    supports_images = True
    supports_text = True
    supports_search = True

    BASE_URL = "https://www.shidianguji.com"
    _CDN_HOST = "byteimg.com"

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    # Role words to strip from author names
    _ROLE_WORDS = re.compile(r'[撰注疏輯校點箋補纂訂譯編釋]$')

    # Lazy-loaded OpenCC converters
    _s2t: Optional[object] = None
    _t2s: Optional[object] = None
    _variant_map: Optional[dict[str, str]] = None

    def __init__(self, config=None):
        super().__init__(config)
        self._pw = None
        self._browser = None
        self._context = None

    def _check_playwright(self):
        if not HAS_PLAYWRIGHT:
            raise DownloadError(
                "playwright is required for 识典古籍. "
                "Install with: pip install playwright && playwright install chromium"
            )

    def extract_book_id(self, url: str) -> str:
        """Extract book ID from URL."""
        match = re.search(r'/book/([a-zA-Z0-9_]+)', url)
        if match:
            return match.group(1)
        raise MetadataExtractionError(f"Could not extract book ID from URL: {url}")

    async def _ensure_browser(self):
        """Ensure a persistent browser instance is available (reuse across calls)."""
        if self._browser and self._browser.is_connected():
            return
        self._check_playwright()
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(headless=True)
        except Exception as e:
            await self._pw.stop()
            self._pw = None
            raise DownloadError(
                "Chromium 浏览器未安装。请运行: playwright install chromium"
            ) from e
        self._context = await self._browser.new_context(
            user_agent=self._USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )

    async def _close_browser(self):
        """Close the persistent browser instance."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._context = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def _launch_browser(self):
        """Start Playwright, launch Chromium, return (pw, browser, context).

        Used by get_metadata / get_image_list / get_structured_text which
        manage their own browser lifecycle.
        """
        self._check_playwright()
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as e:
            await pw.stop()
            raise DownloadError(
                "Chromium 浏览器未安装。请运行: playwright install chromium"
            ) from e
        context = await browser.new_context(
            user_agent=self._USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        return pw, browser, context

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Fetch book metadata by intercepting the reader-book API."""
        self._check_playwright()

        book_info: dict = {}
        api_done = asyncio.Event()

        pw, browser, context = await self._launch_browser()
        try:
            page = await context.new_page()

            async def on_response(response):
                if "/api/ancientlib/read/reader-book/get/" in response.url:
                    try:
                        data = await response.json()
                        if data.get("errorCode") == 0:
                            book_info.update(data["data"].get("bookInfo", {}))
                            api_done.set()
                    except Exception:
                        pass

            page.on("response", on_response)
            book_url = f"{self.BASE_URL}/zh/book/{book_id}"
            try:
                await page.goto(book_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.warning(f"Page.goto: {e}")

            try:
                await asyncio.wait_for(api_done.wait(), timeout=20.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for metadata API for {book_id}")

        finally:
            await browser.close()
            await pw.stop()

        if not book_info:
            raise MetadataExtractionError(f"Failed to get metadata for {book_id}")

        return self._parse_metadata(book_info, book_id)

    def _parse_metadata(self, info: dict, book_id: str) -> BookMetadata:
        """Convert bookInfo API dict to BookMetadata."""
        metadata = BookMetadata(source_id=book_id)
        metadata.source_url = f"{self.BASE_URL}/zh/book/{book_id}"
        metadata.title = info.get("bookName", "")

        # Dynasty
        metadata.dynasty = info.get("dynastyCategoryName", "")

        # Traditional category hierarchy (cateName field)
        trad_cats = info.get("traditionalCategory", [])
        if trad_cats:
            metadata.category = " / ".join(
                c.get("cateName") or c.get("name", "")
                for c in trad_cats
                if c.get("cateName") or c.get("name")
            )

        # Authors — may be a list or a JSON string
        authors_raw = info.get("authors", [])
        try:
            authors = json.loads(authors_raw) if isinstance(authors_raw, str) else authors_raw
            for a in (authors or []):
                # API uses persName / responsibleTypeStr / dynastyName
                name = a.get("persName") or a.get("name", "")
                role = a.get("responsibleTypeStr") or a.get("role", "")
                dynasty = a.get("dynastyName") or a.get("dynasty", "")
                if name:
                    metadata.creators.append(Creator(name=name, role=role, dynasty=dynasty))
        except (json.JSONDecodeError, TypeError):
            pass

        # Alternative names (may be a list or a comma-separated string)
        add_names = info.get("addNames", "")
        if add_names:
            if isinstance(add_names, list):
                metadata.alt_titles = [n.strip() for n in add_names if n and n.strip()]
            else:
                metadata.alt_titles = [n.strip() for n in str(add_names).split(",") if n.strip()]

        # Total pages
        total_pages = info.get("totalPage", 0)
        if total_pages:
            metadata.pages = total_pages

        # Edition → notes
        edition = info.get("edition", {})
        if edition and edition.get("edition"):
            metadata.notes.append(f"版本: {edition['edition']}")

        metadata.raw_metadata = info
        return metadata

    # ------------------------------------------------------------------
    # Image list
    # ------------------------------------------------------------------

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """
        Collect signed CDN image URLs for all pages.

        Strategy: open book reader in Playwright, intercept byteimg.com requests
        while navigating through all pages with keyboard (→). Each keypress
        advances the reader; the browser fetches the visible page's image from CDN.
        """
        self._check_playwright()

        pages_data: list[dict] = []     # [{pageNum, uri, ...}] from pages/v3 API
        image_map: dict[str, str] = {}  # uri -> full signed CDN URL
        pages_event = asyncio.Event()

        pw, browser, context = await self._launch_browser()
        try:
            page = await context.new_page()

            def _extract_uri_from_cdn_url(url: str) -> Optional[str]:
                """Extract the path URI (e.g. 'read/SBCK001/4/page/…') from a CDN URL."""
                m = re.search(r'/tos-cn-i-[^/]+/(.+?)(?:~|$|\?)', url)
                return m.group(1) if m else None

            async def on_request(request):
                url = request.url
                if self._CDN_HOST in url and "ancientlib" in url and ".webp" in url:
                    uri = _extract_uri_from_cdn_url(url)
                    if uri and uri not in image_map:
                        image_map[uri] = url

            async def on_response(response):
                if "/api/ancientlib/read/book/pages/v3/" in response.url:
                    try:
                        data = await response.json()
                        if data.get("errorCode") == 0:
                            pages_data.extend(data["data"]["pages"])
                            pages_event.set()
                    except Exception:
                        pass

            page.on("request", on_request)
            page.on("response", on_response)

            book_url = f"{self.BASE_URL}/zh/book/{book_id}"
            logger.info(f"[识典古籍] Loading book reader: {book_url}")
            try:
                await page.goto(book_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.warning(f"Page.goto: {e}")

            # Wait for pages list API
            try:
                await asyncio.wait_for(pages_event.wait(), timeout=20.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for pages API for {book_id}")

            total_pages = len(pages_data)
            if total_pages == 0:
                logger.warning("No page data found; returning empty image list")
                return []

            logger.info(f"[识典古籍] Book has {total_pages} pages, navigating to capture image URLs...")

            # Give the first page time to load its image
            await asyncio.sleep(3)

            # Navigate through all pages: press → repeatedly until we have all images
            # The reader preloads 2-3 pages ahead, so we may get several per keypress
            stall_count = 0
            prev_len = len(image_map)
            max_stall = 15      # stop if 15 consecutive keypresses yield no new images

            for nav in range(total_pages + 20):
                if len(image_map) >= total_pages:
                    break
                await page.keyboard.press("ArrowRight")
                await asyncio.sleep(1.0)

                if len(image_map) == prev_len:
                    stall_count += 1
                    if stall_count >= max_stall:
                        logger.warning(
                            f"[识典古籍] No new images after {max_stall} keypresses; stopping early "
                            f"({len(image_map)}/{total_pages} captured)"
                        )
                        break
                else:
                    stall_count = 0
                    prev_len = len(image_map)

                if (nav + 1) % 20 == 0:
                    logger.info(
                        f"[识典古籍] Nav {nav+1}: {len(image_map)}/{total_pages} image URLs captured"
                    )

            logger.info(f"[识典古籍] Captured {len(image_map)}/{total_pages} signed image URLs")

        finally:
            await browser.close()
            await pw.stop()

        # Build Resource list ordered by pageNum
        resources: List[Resource] = []
        for pg in sorted(pages_data, key=lambda x: x.get("pageNum", 0)):
            uri = pg.get("uri", "")
            page_num = pg.get("pageNum", 0)

            # Exact match first, then substring match
            signed_url = image_map.get(uri)
            if not signed_url:
                for img_uri, img_url in image_map.items():
                    if uri and (uri in img_uri or img_uri in uri):
                        signed_url = img_url
                        break

            if signed_url:
                resources.append(Resource(
                    url=signed_url,
                    resource_type=ResourceType.IMAGE,
                    order=page_num,
                    page=str(page_num),
                    filename=f"{page_num:04d}.webp",
                ))
            else:
                logger.warning(f"[识典古籍] No signed URL found for page {page_num} (uri={uri})")

        return resources

    # ------------------------------------------------------------------
    # Structured text
    # ------------------------------------------------------------------

    async def get_structured_text(
        self,
        book_id: str,
        index_id: str = "",
        progress_callback: Callable[[int, int], None] = None,
    ) -> Optional[StructuredText]:
        """
        Collect paragraph text for all chapters.

        Navigates through the reader to trigger paragraphs/v2 API calls.
        Text content is unencrypted (contentEncryptType: 0).
        """
        self._check_playwright()

        all_paragraphs: list[dict] = []
        chapters_seen: set[str] = set()
        book_info: dict = {}

        pw, browser, context = await self._launch_browser()
        try:
            page = await context.new_page()

            async def on_response(response):
                url = response.url
                if "/api/ancientlib/read/reader-book/get/" in url:
                    try:
                        data = await response.json()
                        if data.get("errorCode") == 0:
                            book_info.update(data["data"].get("bookInfo", {}))
                    except Exception:
                        pass
                elif "/api/ancientlib/read/book/paragraphs/v2" in url:
                    try:
                        data = await response.json()
                        if data.get("errorCode") == 0:
                            paras = data["data"].get("paragraphs", [])
                            chapter_id = data["data"].get("chapterId") or (
                                paras[0].get("chapterId") if paras else ""
                            )
                            key = str(chapter_id)
                            if key and key not in chapters_seen:
                                all_paragraphs.extend(paras)
                                chapters_seen.add(key)
                    except Exception:
                        pass

            page.on("response", on_response)

            book_url = f"{self.BASE_URL}/zh/book/{book_id}"
            logger.info(f"[识典古籍] Loading book for text extraction: {book_url}")
            try:
                await page.goto(book_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.warning(f"Page.goto: {e}")

            await asyncio.sleep(5)

            # Determine chapter count from catalog
            catalog_raw = book_info.get("catalog", "[]")
            try:
                catalog = json.loads(catalog_raw) if isinstance(catalog_raw, str) else catalog_raw
            except Exception:
                catalog = []
            total_chapters = len(catalog) or 99  # fallback if catalog empty

            logger.info(f"[识典古籍] Book has {total_chapters} chapters, collecting text...")

            stall_count = 0
            prev_len = len(chapters_seen)

            for nav in range(total_chapters * 5 + 50):
                if len(chapters_seen) >= total_chapters:
                    break
                await page.keyboard.press("ArrowRight")
                await asyncio.sleep(1.2)

                if len(chapters_seen) == prev_len:
                    stall_count += 1
                    if stall_count >= 20:
                        logger.warning(
                            f"[识典古籍] No new chapters after 20 keypresses; stopping "
                            f"({len(chapters_seen)}/{total_chapters} chapters collected)"
                        )
                        break
                else:
                    stall_count = 0
                    prev_len = len(chapters_seen)
                    if progress_callback:
                        progress_callback(len(chapters_seen), total_chapters)

                if (nav + 1) % 30 == 0:
                    logger.info(
                        f"[识典古籍] Nav {nav+1}: {len(chapters_seen)}/{total_chapters} chapters"
                    )

            logger.info(
                f"[识典古籍] Collected {len(all_paragraphs)} paragraphs "
                f"from {len(chapters_seen)} chapters"
            )

        finally:
            await browser.close()
            await pw.stop()

        if not all_paragraphs:
            return None

        parser = ShidianGujiParser()
        url = f"{self.BASE_URL}/zh/book/{book_id}"
        meta = {
            "title": book_info.get("bookName", ""),
            "authors_json": book_info.get("authors", "[]"),
            "dynasty": book_info.get("dynastyCategoryName", ""),
            "catalog": catalog if isinstance(catalog, list) else [],
        }
        return parser.parse(all_paragraphs, book_id, url, meta)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search 识典古籍 for books matching *query*.

        Navigates to the search page in Playwright and intercepts the
        ``/api/ancientlib/read/search/book/v1`` response.
        """
        all_books = await self._search_books(query)

        total_hits = len(all_books)
        page_results = all_books[offset:offset + limit]
        has_more = (offset + limit) < total_hits

        results = []
        for b in page_results:
            book_id = b.get("bookId", "")
            book_name = b.get("bookName", "")
            authors = b.get("authors", [])
            dynasty = b.get("dynastyCategoryName", "")
            author_str = self._format_authors(authors)
            snippet = f"（{dynasty}）{author_str}" if dynasty else author_str
            results.append(SearchResult(
                title=book_name,
                url=f"{self.BASE_URL}/book/{book_id}" if book_id else "",
                snippet=snippet,
                source_site=self.site_id,
            ))

        return SearchResponse(
            query=query,
            results=results,
            total_hits=total_hits,
            has_more=has_more,
            continuation=str(offset + limit) if has_more else "",
        )

    async def _search_books(self, query: str) -> list[dict]:
        """Execute a search via Playwright and return the raw book list.

        Strategy:
        1. Navigate to /zh/search/{query} (SSR page with full-text results)
        2. Click the "搜书籍" tab to trigger book search API
        3. Intercept /api/ancientlib/read/search/book/v1 response
        4. Return list of book dicts from searchBookList

        Returns list of dicts with keys: bookId, bookName, authors,
        dynastyCategoryName, addNames, etc.  Each entry is the "book"
        sub-dict unwrapped from the API response.
        """
        await self._ensure_browser()

        search_results: list[dict] = []
        api_done = asyncio.Event()

        page = await self._context.new_page()
        try:
            async def on_response(response):
                if "/api/ancientlib/read/search/book/v1" in response.url:
                    try:
                        data = await response.json()
                        if data.get("errorCode") == 0:
                            book_list = data.get("data", {}).get(
                                "searchBookList", []
                            )
                            for item in book_list:
                                book = item.get("book", item)
                                search_results.append(book)
                            api_done.set()
                    except Exception:
                        api_done.set()

            page.on("response", on_response)

            encoded = urllib.parse.quote(query)
            search_url = f"{self.BASE_URL}/zh/search/{encoded}"
            logger.debug(f"[识典古籍] Searching: {search_url}")
            try:
                await page.goto(
                    search_url, wait_until="networkidle", timeout=30000
                )
            except Exception as e:
                logger.warning(f"[识典古籍] Search page.goto: {e}")

            # Click the "搜书籍" tab to trigger the book search API
            try:
                book_tab = page.locator(
                    'div.semi-tabs-tab:has-text("搜书籍")'
                )
                await book_tab.click(timeout=5000)
            except Exception as e:
                logger.warning(f"[识典古籍] Could not click book tab: {e}")

            try:
                await asyncio.wait_for(api_done.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning(
                    f"[识典古籍] Timeout waiting for book search API "
                    f"for '{query}'"
                )

        finally:
            await page.close()

        return search_results

    @staticmethod
    def _format_authors(authors) -> str:
        """Format authors list/string to a readable string."""
        if isinstance(authors, str):
            try:
                authors = json.loads(authors)
            except (json.JSONDecodeError, TypeError):
                return authors
        if not isinstance(authors, list):
            return ""
        names = []
        for a in authors:
            if isinstance(a, dict):
                names.append(a.get("persName") or a.get("name", ""))
            elif isinstance(a, str):
                names.append(a)
        return "、".join(n for n in names if n)

    @staticmethod
    def _extract_author_names(authors) -> list[str]:
        """Extract author name strings from the API authors field."""
        if isinstance(authors, str):
            try:
                authors = json.loads(authors)
            except (json.JSONDecodeError, TypeError):
                return [authors] if authors else []
        if not isinstance(authors, list):
            return []
        names = []
        for a in authors:
            if isinstance(a, dict):
                name = a.get("persName") or a.get("name", "")
                if name:
                    names.append(name)
            elif isinstance(a, str) and a:
                names.append(a)
        return names

    # ------------------------------------------------------------------
    # match_book — exact title + author matching for book index
    # ------------------------------------------------------------------

    async def match_book(
        self,
        title: str,
        authors: list[str] | None = None,
        delay: float = 1.0,
    ) -> list[MatchedResource]:
        """Match a book by title + author against 识典古籍.

        Strategy:
        1. Generate title variants (simplified/traditional)
        2. Search each variant via Playwright
        3. Filter by exact title match
        4. Verify author/dynasty if authors provided
        5. Return matched resources

        Args:
            title: Book title (e.g. "周易")
            authors: Author names for filtering (e.g. ["王弼"])
            delay: Seconds between search requests

        Returns:
            List of matched resources.
        """
        authors = authors or []
        found: list[MatchedResource] = []
        seen_ids: set[str] = set()

        def add_result(book_id: str, book_name: str, details: str = "",
                       quality: dict | None = None):
            if book_id in seen_ids:
                return
            seen_ids.add(book_id)
            found.append(MatchedResource(
                id="shidianguji",
                name="识典古籍",
                url=f"{self.BASE_URL}/book/{book_id}",
                details=details,
                quality=quality or {},
            ))

        # Generate title variants
        title_variants = self._generate_title_variants(title)
        search_queries = list(dict.fromkeys(title_variants))[:3]

        # Search with each variant
        all_books: list[dict] = []
        seen_book_ids: set[str] = set()

        for i, query in enumerate(search_queries):
            if i > 0:
                await asyncio.sleep(delay)
            books = await self._search_books(query)
            for b in books:
                bid = b.get("bookId", "")
                if bid and bid not in seen_book_ids:
                    seen_book_ids.add(bid)
                    all_books.append(b)
            # If first query has exact title matches, skip variants
            if books and any(
                self._title_matches(b.get("bookName", ""), title_variants)
                for b in books
            ):
                break

        # Filter by exact title match
        candidates = [
            b for b in all_books
            if self._title_matches(b.get("bookName", ""), title_variants)
        ]

        if not candidates:
            return found

        def _extract_details_and_quality(b: dict) -> tuple[str, dict]:
            dynasty = b.get("dynastyCategoryName", "")
            author_str = self._format_authors(b.get("authors", []))
            details = ""
            if dynasty and author_str:
                details = f"（{dynasty}）{author_str}"
            elif author_str:
                details = author_str
            extra = b.get("extra", {})
            quality = {
                "version": b.get("version", 0),
                "total_page": b.get("totalPage", 0),
                "paragraph_count": extra.get("paragraphNumber", 0),
                "has_translation": extra.get("translateStatus", 0) >= 2,
                "edition": b.get("edition", {}).get("edition", ""),
            }
            return details, quality

        # No authors to filter — return all title-matched candidates
        if not authors:
            for b in candidates:
                book_id = b.get("bookId", "")
                book_name = b.get("bookName", "")
                details, quality = _extract_details_and_quality(b)
                add_result(book_id, book_name, details, quality)
            return found

        # With authors: classify candidates by match quality
        author_matched: list[dict] = []
        surname_matched: list[dict] = []
        unmatched: list[dict] = []

        for b in candidates:
            result_authors = self._extract_author_names(b.get("authors", []))
            if not result_authors:
                author_matched.append(b)
            elif self._author_matches(result_authors, authors):
                author_matched.append(b)
            elif self._surname_matches(result_authors, authors):
                surname_matched.append(b)
            else:
                unmatched.append(b)

        # Use strict matches if any; else surname; else accept all if ≤ 3
        if author_matched:
            accepted = author_matched
        elif surname_matched:
            accepted = surname_matched
        elif len(unmatched) <= 3:
            accepted = unmatched
        else:
            accepted = []

        for b in accepted:
            book_id = b.get("bookId", "")
            book_name = b.get("bookName", "")
            details, quality = _extract_details_and_quality(b)
            add_result(book_id, book_name, details, quality)

        return found

    # ------------------------------------------------------------------
    # Title / author matching helpers (shared with CText pattern)
    # ------------------------------------------------------------------

    @classmethod
    def _get_s2t(cls):
        if cls._s2t is None:
            try:
                from opencc import OpenCC
                cls._s2t = OpenCC('s2t')
            except ImportError:
                return None
        return cls._s2t

    @classmethod
    def _get_t2s(cls):
        if cls._t2s is None:
            try:
                from opencc import OpenCC
                cls._t2s = OpenCC('t2s')
            except ImportError:
                return None
        return cls._t2s

    @classmethod
    def _get_variant_map(cls) -> dict[str, str]:
        """Load CJK variant→standard character mapping from OpenCC dicts."""
        if cls._variant_map is not None:
            return cls._variant_map

        import os
        vmap: dict[str, str] = {}
        try:
            import opencc
            dict_dir = os.path.join(os.path.dirname(opencc.__file__), 'dictionary')

            jp_path = os.path.join(dict_dir, 'JPVariants.txt')
            if os.path.exists(jp_path):
                with open(jp_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        parts = line.strip().split('\t')
                        if len(parts) == 2:
                            std = parts[0]
                            for v in parts[1].split(' '):
                                if len(v) == 1 and len(std) == 1 and v != std:
                                    vmap[v] = std

            for fn in ('TWVariantsRev.txt', 'HKVariantsRev.txt'):
                fp = os.path.join(dict_dir, fn)
                if os.path.exists(fp):
                    with open(fp, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split('\t')
                            if len(parts) == 2:
                                v = parts[0]
                                std = parts[1].split(' ')[0]
                                if len(v) == 1 and len(std) == 1 and v != std:
                                    vmap[v] = std
        except Exception:
            pass

        cls._variant_map = vmap
        return vmap

    @classmethod
    def _normalize_variants(cls, text: str) -> str:
        """Normalize CJK variant characters to standard traditional forms."""
        vmap = cls._get_variant_map()
        if vmap:
            text = ''.join(vmap.get(ch, ch) for ch in text)
        s2t = cls._get_s2t()
        if s2t:
            try:
                text = s2t.convert(text)
            except Exception:
                pass
        return text

    def _generate_title_variants(self, title: str) -> list[str]:
        """Generate CJK variant titles (simplified/traditional + variants)."""
        variants: set[str] = {title}

        s2t = self._get_s2t()
        t2s = self._get_t2s()
        if s2t:
            try:
                variants.add(s2t.convert(title))
            except Exception:
                pass
        if t2s:
            try:
                variants.add(t2s.convert(title))
            except Exception:
                pass

        # Removable prefixes common in Siku titles
        removable = ['欽定', '御定', '御纂', '御製', '御選']
        base_variants = set(variants)
        for prefix in removable:
            for v in base_variants:
                if v.startswith(prefix):
                    variants.add(v[len(prefix):])

        return list(variants)

    def _title_matches(
        self, candidate: str, title_variants: list[str],
    ) -> bool:
        """Check if candidate title matches any of the title variants."""
        norm_candidate = self._normalize_variants(candidate)
        candidate_forms = {candidate, norm_candidate}
        t2s = self._get_t2s()
        if t2s:
            try:
                candidate_forms.add(t2s.convert(norm_candidate))
            except Exception:
                pass

        norm_variants: set[str] = set(title_variants)
        for v in title_variants:
            norm_variants.add(self._normalize_variants(v))

        for cf in candidate_forms:
            for v in norm_variants:
                if cf == v:
                    return True
        return False

    def _author_matches(
        self, result_authors: list[str], query_authors: list[str],
    ) -> bool:
        """Check if any result author matches any query author.

        Handles role-word stripping, variant normalization, and
        simplified↔traditional conversion.
        """
        result_forms: set[str] = set()
        for ra in result_authors:
            clean = self._ROLE_WORDS.sub('', ra)
            norm = self._normalize_variants(clean)
            result_forms.add(clean)
            result_forms.add(norm)
            t2s = self._get_t2s()
            if t2s:
                try:
                    result_forms.add(t2s.convert(norm))
                except Exception:
                    pass

        for qa in query_authors:
            clean_qa = self._ROLE_WORDS.sub('', qa)
            norm_qa = self._normalize_variants(clean_qa)
            qa_forms = {clean_qa, norm_qa}
            t2s = self._get_t2s()
            if t2s:
                try:
                    qa_forms.add(t2s.convert(norm_qa))
                except Exception:
                    pass

            for rf in result_forms:
                for qf in qa_forms:
                    if rf == qf:
                        return True
                    if qf in rf or rf in qf:
                        return True
        return False

    def _surname_matches(
        self, result_authors: list[str], query_authors: list[str],
    ) -> bool:
        """Check if result authors share a surname with any query author."""
        result_surnames: set[str] = set()
        for ra in result_authors:
            clean = self._ROLE_WORDS.sub('', ra)
            norm = self._normalize_variants(clean)
            if norm:
                result_surnames.add(norm[0])
                t2s = self._get_t2s()
                if t2s:
                    try:
                        result_surnames.add(t2s.convert(norm[0]))
                    except Exception:
                        pass

        for qa in query_authors:
            clean_qa = self._ROLE_WORDS.sub('', qa)
            norm_qa = self._normalize_variants(clean_qa)
            if norm_qa:
                if norm_qa[0] in result_surnames:
                    return True
                t2s = self._get_t2s()
                if t2s:
                    try:
                        if t2s.convert(norm_qa[0]) in result_surnames:
                            return True
                    except Exception:
                        pass
        return False

    # ------------------------------------------------------------------

    async def close(self):
        """Clean up persistent browser if any."""
        await self._close_browser()
