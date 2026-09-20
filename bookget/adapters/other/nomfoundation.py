# 喃遺産保存会 数字图书馆 (Vietnamese Nôm Preservation Foundation)
# https://lib.nomfoundation.org/
#
# 越南汉喃古籍（与越南国家图书馆 NLV 合作数字化）。No IIIF and no API: the
# page view carries the image path and a "Page N of M" counter.
#
# URL patterns:
#   - Volume: https://lib.nomfoundation.org/collection/{c}/volume/{v}
#   - Page:   https://lib.nomfoundation.org/collection/{c}/volume/{v}/page/{n}
#   - Image:  https://lib.nomfoundation.org/site_media/nom/{prefix}/
#             {jpeg|large}/{prefix}-{page:03d}.jpg

import html as html_module
import re
from typing import List, Optional
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...logger import logger
from ...exceptions import MetadataExtractionError

_VOLUME_RE = re.compile(r'/collection/(\d+)/volume/(\d+)')
_COUNT_RE = re.compile(r'Page\s+\d+\s+of\s+(\d+)', re.IGNORECASE)
_IMAGE_RE = re.compile(
    r'<img[^>]+src="(/site_media/nom/([^/"]+)/jpeg/[^"]*?-(\d+)\.jpg)"[^>]*usemap')
_TITLE_RE = re.compile(r'<title>([^<]*)</title>', re.IGNORECASE)

_BASE = "https://lib.nomfoundation.org"

# The viewer's page count undercounts: volume 1/1 says "Page 1 of 5" but
# images -006..-008 exist too (trailing covers/plates the viewer hides).
# Probe a bounded tail past the counted pages rather than either trusting
# the count (loses pages) or probing open-endedly (a grind).
_TAIL_PROBE_LIMIT = 12


@AdapterRegistry.register
class NomFoundationAdapter(BaseSiteAdapter):
    """Adapter for the Vietnamese Nôm Preservation Foundation library."""

    site_name = "喃遺産保存会 汉喃古籍 (Nom Foundation)"
    site_id = "nomfoundation"
    site_domains = ["lib.nomfoundation.org"]

    supports_iiif = False
    supports_images = True
    supports_text = False

    default_headers = {"Referer": f"{_BASE}/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # The site is slow; a short default timeout turns healthy pages
            # into spurious failures.
            self._session = aiohttp.ClientSession(
                headers=self.get_headers(),
                timeout=aiohttp.ClientTimeout(total=120))
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        match = _VOLUME_RE.search(url)
        if not match:
            raise MetadataExtractionError(
                f"喃遗产地址里取不到 collection/volume：{url}\n"
                f"（条目地址形如 /collection/1/volume/1）")
        return f"{match.group(1)}_{match.group(2)}"

    def page_url(self, book_id: str, page: int = 1) -> str:
        collection, _, volume = book_id.partition("_")
        return f"{_BASE}/collection/{collection}/volume/{volume}/page/{page}"

    @staticmethod
    def image_url(prefix: str, page: int) -> str:
        # "large" is the full-resolution derivative; "jpeg" is the viewer size.
        return f"{_BASE}/site_media/nom/{prefix}/large/{prefix}-{page:03d}.jpg"

    @staticmethod
    def parse_page(html: str):
        """Return (title, prefix, counted page total) from a page view."""
        title_match = _TITLE_RE.search(html)
        # Titles carry HTML entities (&bull; between the Nôm and romanised
        # forms) — unescape before anything reads or matches them.
        title = html_module.unescape(title_match.group(1)).strip() if title_match else ""
        # "<work> • <romanised> • Page 1" -> drop the trailing page marker
        title = re.sub(r'\s*•\s*Page\s*\d+\s*$', "", title).strip()

        image = _IMAGE_RE.search(html)
        prefix = image.group(2) if image else ""

        count = _COUNT_RE.search(html)
        return title, prefix, int(count.group(1)) if count else 0

    async def _fetch(self, url: str) -> str:
        session = await self.get_session()
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text(errors="replace")
        except Exception as e:
            raise MetadataExtractionError(
                f"[nomfoundation] 取页面失败：{url}（{e}）") from e

    async def _exists(self, url: str) -> bool:
        session = await self.get_session()
        try:
            async with session.head(url) as response:
                return response.status == 200
        except Exception:
            return False

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        title, _, count = self.parse_page(await self._fetch(self.page_url(book_id)))

        metadata = BookMetadata(
            source_id=book_id,
            source_url=self.page_url(book_id),
            source_site=self.site_id,
            index_id=index_id,
        )
        metadata.title = title or f"Nom {book_id}"
        metadata.collection_unit = "Vietnamese Nôm Preservation Foundation"
        metadata.pages = count
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        page_url = self.page_url(book_id)
        _, prefix, count = self.parse_page(await self._fetch(page_url))

        if not prefix:
            raise MetadataExtractionError(
                f"[nomfoundation] 页面里没有影像：{page_url}\n"
                f"（该册可能未数字化，或站点结构已改）")

        pages = list(range(1, max(count, 1) + 1))

        # Pick up the trailing images the viewer does not count.
        extra = 0
        page = pages[-1] + 1
        while extra < _TAIL_PROBE_LIMIT and await self._exists(
                self.image_url(prefix, page)):
            pages.append(page)
            page += 1
            extra += 1
        if extra:
            logger.info(
                f"Nom {book_id}: 阅览器报 {count} 页，实际另有 {extra} 张尾图")

        logger.info(f"Nom {book_id} ({prefix}): {len(pages)} images")
        return [
            Resource(
                url=self.image_url(prefix, page),
                resource_type=ResourceType.IMAGE,
                order=index,
                page=str(page),
                filename=f"{prefix}-{page:03d}.jpg",
            )
            for index, page in enumerate(pages, start=1)
        ]
