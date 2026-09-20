# 早稲田大学図書館 古典籍総合データベース (Waseda University Library)
# https://www.wul.waseda.ac.jp/kotenseki/
#
# NOTE: this used to be filed as a "grind" site — the catalogue page links
# only the first page's thumbnail, so enumerating pages looked like it meant
# probing 404s. It does not: the archive host publishes a per-book directory
# index listing every fascicle, and each fascicle's HTML links every page
# image explicitly. Measured 2026-09-20; per-fascicle PDFs exist too
# (bunko01_01501_0001.pdf, 44.5 MB), contrary to the older note that said
# whole/per-volume PDFs 404.
#
# URL patterns:
#   - Catalogue: https://www.wul.waseda.ac.jp/kotenseki/html/{grp}/{id}/index.html
#   - Book dir:  https://archive.wul.waseda.ac.jp/kosho/{grp}/{id}/
#   - Fascicle:  .../{id}_{vol}/{id}_{vol}.html   (+ .pdf)
#   - Image:     .../{id}_{vol}/{id}_{vol}_p{page:04d}.jpg
#                (the "…s.jpg" variant is a thumbnail)

import re
from typing import List, Optional
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...logger import logger
from ...exceptions import MetadataExtractionError

_ID_RE = re.compile(r'/(?:html|kosho)/[^/]+/([A-Za-z0-9]+_\d+)')
_VOLUME_RE = re.compile(r'href=["\']?(([A-Za-z0-9]+_\d+_\d+)/\2\.html)')
_PAGE_RE = re.compile(r'href=["\']?([A-Za-z0-9_]+_p(\d+)\.jpg)')
_TITLE_RE = re.compile(r'<title>([^<]*)</title>', re.IGNORECASE)

_ARCHIVE = "https://archive.wul.waseda.ac.jp/kosho"
_CATALOGUE = "https://www.wul.waseda.ac.jp/kotenseki/html"


@AdapterRegistry.register
class WasedaAdapter(BaseSiteAdapter):
    """Adapter for Waseda University Library's classical books database."""

    site_name = "早稲田大学図書館 古典籍 (Waseda)"
    site_id = "waseda"
    site_domains = ["wul.waseda.ac.jp"]

    supports_iiif = False
    supports_images = True
    supports_pdf = True
    supports_text = False

    default_headers = {"Referer": "https://www.wul.waseda.ac.jp/kotenseki/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self.get_headers(),
                timeout=aiohttp.ClientTimeout(total=120))
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        match = _ID_RE.search(url)
        if not match:
            raise MetadataExtractionError(
                f"早稲田地址里取不到书号：{url}\n"
                f"（条目地址形如 /kotenseki/html/bunko01/bunko01_01501/index.html）")
        return match.group(1)

    @staticmethod
    def group_of(book_id: str) -> str:
        """bunko01_01501 -> bunko01 (the collection directory)."""
        return book_id.rsplit("_", 1)[0]

    def book_dir(self, book_id: str) -> str:
        return f"{_ARCHIVE}/{self.group_of(book_id)}/{book_id}/"

    def catalogue_url(self, book_id: str) -> str:
        return f"{_CATALOGUE}/{self.group_of(book_id)}/{book_id}/index.html"

    async def _fetch(self, url: str) -> str:
        session = await self.get_session()
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                raw = await response.read()
        except Exception as e:
            raise MetadataExtractionError(
                f"[waseda] 取页面失败：{url}（{e}）") from e
        for encoding in ("utf-8", "shift_jis", "euc-jp"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def parse_book_dir(html: str) -> List[str]:
        """Fascicle ids, in listing order, from the per-book directory page."""
        seen = []
        for _, volume_id in _VOLUME_RE.findall(html):
            if volume_id not in seen:
                seen.append(volume_id)
        return sorted(seen)

    @staticmethod
    def parse_volume(html: str) -> List[str]:
        """Page image filenames, deduplicated and in page order.

        Each page is linked twice on the fascicle page, and the thumbnails
        ("…s.jpg") are not linked at all, so dedupe and sort by page number.
        """
        pages = {name: int(number) for name, number in _PAGE_RE.findall(html)}
        return sorted(pages, key=pages.get)

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        html = await self._fetch(self.catalogue_url(book_id))
        title = _TITLE_RE.search(html)

        metadata = BookMetadata(
            source_id=book_id,
            source_url=self.catalogue_url(book_id),
            source_site=self.site_id,
            index_id=index_id,
        )
        if not (title and title.group(1).strip()):
            # The catalogue pages carry the work's name in the first heading
            # rather than <title>.
            heading = re.search(r'<h[12][^>]*>([^<]+)</h[12]>', html)
            metadata.title = heading.group(1).strip() if heading else book_id
        else:
            metadata.title = title.group(1).strip()
        metadata.collection_unit = "早稲田大学図書館"
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        book_dir = self.book_dir(book_id)
        volumes = self.parse_book_dir(await self._fetch(book_dir))
        if not volumes:
            raise MetadataExtractionError(
                f"[waseda] 目录页里没有册：{book_dir}\n"
                f"（该书可能未数字化，或 archive 站结构已改）")

        resources: List[Resource] = []
        for volume_id in volumes:
            volume_html = await self._fetch(f"{book_dir}{volume_id}/{volume_id}.html")
            pages = self.parse_volume(volume_html)
            if not pages:
                logger.warning(f"[waseda] {volume_id} 页面里没有图片链接，跳过")
                continue
            for name in pages:
                resources.append(Resource(
                    url=f"{book_dir}{volume_id}/{name}",
                    resource_type=ResourceType.IMAGE,
                    order=len(resources) + 1,
                    page=str(len(resources) + 1),
                    filename=name,
                ))

        if not resources:
            raise MetadataExtractionError(
                f"[waseda] {book_id} 的每一册都没有图片链接：{book_dir}")

        logger.info(f"Waseda {book_id}: {len(volumes)} 冊 / {len(resources)} images")
        return resources

    async def get_pdf_url(self, book_id: str) -> Optional[str]:
        """The first fascicle's PDF; the site has one per fascicle."""
        volumes = self.parse_book_dir(await self._fetch(self.book_dir(book_id)))
        if not volumes:
            return None
        return f"{self.book_dir(book_id)}{volumes[0]}/{volumes[0]}.pdf"
