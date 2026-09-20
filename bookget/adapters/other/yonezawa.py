# 米沢市立図書館 デジタルライブラリー (Yonezawa City Library)
# https://www.library.yonezawa.yamagata.jp/dg/
#
# 興譲館文庫 等の漢籍・和古書。No IIIF and no API: the viewer page carries a
# `var dir` and one <option> per fascicle whose value is "{volumeId},{pages}",
# which is everything needed to build the image URLs directly.
#
# URL patterns:
#   - Item:   https://www.library.yonezawa.yamagata.jp/dg/AA001.html
#   - Viewer: https://www.library.yonezawa.yamagata.jp/dg/AA001_view.html
#   - Image:  https://www.library.yonezawa.yamagata.jp/dg/
#             data/{book}/{vol3}/{volumeId}_{page:03d}.jpg

import re
from typing import List, Optional
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...logger import logger
from ...exceptions import MetadataExtractionError

_BOOK_RE = re.compile(r'/dg/([A-Za-z]{1,3}\d+)(?:_view)?\.html', re.IGNORECASE)
_DIR_RE = re.compile(r'var\s+dir\s*=\s*["\']([^"\']+)["\']')
# <option value="AA001001,059"> -> fascicle AA001001 has 59 pages
_VOLUME_RE = re.compile(r'<option[^>]*value=["\']?([A-Za-z0-9]+),(\d+)')
_TITLE_RE = re.compile(r'<title>([^<]*)</title>', re.IGNORECASE)

_BASE = "https://www.library.yonezawa.yamagata.jp/dg"


def _decode(raw: bytes) -> str:
    """The gallery mixes UTF-8 and Shift_JIS pages."""
    for encoding in ("utf-8", "shift_jis", "euc-jp"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@AdapterRegistry.register
class YonezawaAdapter(BaseSiteAdapter):
    """Adapter for the Yonezawa City Library digital gallery."""

    site_name = "米沢市立図書館 デジタルライブラリー (Yonezawa)"
    site_id = "yonezawa"
    site_domains = ["library.yonezawa.yamagata.jp"]

    supports_iiif = False
    supports_images = True
    supports_text = False

    default_headers = {"Referer": f"{_BASE}/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        match = _BOOK_RE.search(url)
        if not match:
            raise MetadataExtractionError(
                f"米沢デジタルライブラリー地址里取不到书号：{url}\n"
                f"（条目地址形如 /dg/AA001.html）")
        return match.group(1).upper()

    async def _fetch(self, url: str) -> str:
        session = await self.get_session()
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                return _decode(await response.read())
        except Exception as e:
            raise MetadataExtractionError(
                f"[yonezawa] 取页面失败：{url}（{e}）") from e

    @staticmethod
    def parse_viewer(html: str):
        """Return (image dir, [(volume id, page count)]) from a viewer page."""
        directory = _DIR_RE.search(html)
        volumes = [(vol, int(pages)) for vol, pages in _VOLUME_RE.findall(html)]
        return (directory.group(1) if directory else ""), volumes

    def image_url(self, directory: str, volume_id: str, page: int) -> str:
        # The per-fascicle folder is the fascicle number, i.e. the last three
        # digits of the volume id: AA001001 -> data/AA001/001/
        return f"{_BASE}/{directory}{volume_id[-3:]}/{volume_id}_{page:03d}.jpg"

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        html = await self._fetch(f"{_BASE}/{book_id}.html")
        title = _TITLE_RE.search(html)

        viewer = await self._fetch(f"{_BASE}/{book_id}_view.html")
        _, volumes = self.parse_viewer(viewer)

        metadata = BookMetadata(
            source_id=book_id,
            source_url=f"{_BASE}/{book_id}.html",
            source_site=self.site_id,
            index_id=index_id,
        )
        metadata.title = title.group(1).strip() if title else book_id
        metadata.collection_unit = "米沢市立図書館"
        metadata.pages = sum(pages for _, pages in volumes)
        metadata.volume_info = f"{len(volumes)} 冊" if volumes else ""
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        viewer_url = f"{_BASE}/{book_id}_view.html"
        html = await self._fetch(viewer_url)
        directory, volumes = self.parse_viewer(html)

        if not directory or not volumes:
            raise MetadataExtractionError(
                f"[yonezawa] 阅览页里没有册目录：{viewer_url}\n"
                f"（页面结构可能已改版；原本应有 var dir 与 <option value=\"册号,页数\">）")

        resources: List[Resource] = []
        for volume_id, pages in volumes:
            for page in range(1, pages + 1):
                order = len(resources) + 1
                resources.append(Resource(
                    url=self.image_url(directory, volume_id, page),
                    resource_type=ResourceType.IMAGE,
                    order=order,
                    page=str(page),
                    filename=f"{volume_id}_{page:03d}.jpg",
                ))

        logger.info(
            f"Yonezawa {book_id}: {len(volumes)} 冊 / {len(resources)} images")
        return resources
