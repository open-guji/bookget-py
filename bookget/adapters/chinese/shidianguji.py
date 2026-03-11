# 识典古籍 (Shidianguji) Adapter
# https://www.shidianguji.com/
#
# Uses Playwright browser automation to bypass ByteDance SecSDK anti-bot protection.
# SecSDK generates device fingerprints (verifyFp / a_bogus) required for all API calls.

import re
import asyncio
import json
from typing import List, Optional, Callable

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
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

    BASE_URL = "https://www.shidianguji.com"
    _CDN_HOST = "byteimg.com"

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

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

    async def _launch_browser(self):
        """Start Playwright, launch Chromium, return (pw, browser, context)."""
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
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

    async def close(self):
        """No persistent resources."""
        pass
