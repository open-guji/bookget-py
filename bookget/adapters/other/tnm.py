# 東京国立博物館デジタルライブラリー (Tokyo National Museum) Adapter
# https://webarchives.tnm.jp/
#
# 和古书、汉籍、洋书数字图书馆。图片走 Zoomify 瓦片金字塔，需拼接（见
# bookget/downloaders/tiles.py）。需要一个会话 cookie（JSESSIONID），先 GET
# 详情页建立。
#
# 流程：
#   1. 详情页 /dlib/detail/{id}（建立会话 + 取标题）
#   2. /dlib/pages/{id} → JSON [{imageid:"L00xxxxx", ...}, ...]（页清单）
#   3. 每页瓦片基址 /dlib/img/{id}/tiles/{imageid}，含 ImageProperties.xml + TileGroup*/
#      → download_zoomify_image 拉全部顶层瓦片拼成整页

import asyncio
import re
from pathlib import Path
from typing import Callable, List, Optional

import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...models.manifest import ManifestNode, NodeStatus
from ...downloaders.tiles import download_zoomify_image
from ...logger import logger
from ...exceptions import MetadataExtractionError

_IMAGEID_RE = re.compile(r'"imageid"\s*:\s*"([^"]+)"')
_TITLE_RE = re.compile(r'<title>([^<]+)</title>', re.IGNORECASE)


@AdapterRegistry.register
class TNMAdapter(BaseSiteAdapter):
    """Adapter for Tokyo National Museum digital library (Zoomify tiles)."""

    site_name = "東京国立博物館 (TNM)"
    site_id = "tnm"
    site_domains = ["webarchives.tnm.jp"]

    supports_iiif = False
    supports_images = True
    supports_text = False

    BASE = "https://webarchives.tnm.jp"
    default_headers = {"Referer": "https://webarchives.tnm.jp/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_book: Optional[str] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _ensure_session(self, book_id: str):
        """GET the detail page once to obtain the JSESSIONID cookie."""
        if self._session_book == book_id:
            return
        session = await self.get_session()
        async with session.get(f"{self.BASE}/dlib/detail/{book_id}") as r:
            await r.read()
        self._session_book = book_id

    def extract_book_id(self, url: str) -> str:
        m = re.search(r'/dlib/detail/(\d+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract TNM id from URL: {url}")

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        session = await self.get_session()
        async with session.get(f"{self.BASE}/dlib/detail/{book_id}") as r:
            r.raise_for_status()
            html = await r.text(errors="ignore")
        self._session_book = book_id
        meta = BookMetadata(
            source_id=book_id,
            source_url=f"{self.BASE}/dlib/detail/{book_id}",
            source_site=self.site_id,
            index_id=index_id,
            collection_unit="東京国立博物館",
        )
        tm = _TITLE_RE.search(html)
        if tm:
            # "東京国立博物館デジタルライブラリー / 傷寒論" → "傷寒論"
            title = tm.group(1)
            if "/" in title:
                title = title.split("/")[-1]
            meta.title = title.strip()
        return meta

    async def _get_image_codes(self, book_id: str) -> List[str]:
        await self._ensure_session(book_id)
        session = await self.get_session()
        async with session.get(f"{self.BASE}/dlib/pages/{book_id}") as r:
            r.raise_for_status()
            txt = await r.text()
        return list(dict.fromkeys(_IMAGEID_RE.findall(txt)))

    async def get_image_list(self, book_id: str) -> List[Resource]:
        codes = await self._get_image_codes(book_id)
        resources: List[Resource] = []
        for i, code in enumerate(codes, 1):
            # url = the Zoomify tiles base for this page (stitched at download time)
            resources.append(Resource(
                url=f"{self.BASE}/dlib/img/{book_id}/tiles/{code}",
                resource_type=ResourceType.IMAGE,
                order=i,
                page=str(i),
                filename=f"{i:04d}.jpg",
            ))
        logger.info(f"[tnm] {book_id}: {len(resources)} pages (Zoomify)")
        return resources

    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """Stitch each page's Zoomify tiles into a full image."""
        images = node.source_data.get("images")
        if not images:
            urls = node.source_data.get("image_urls", [])
            images = [{"url": u, "filename": f"{i + 1:04d}.jpg"}
                      for i, u in enumerate(urls)]
        if not images:
            logger.warning(f"[tnm] node {node.id} has no images")
            node.status = NodeStatus.FAILED
            return node

        await self._ensure_session(book_id)
        session = await self.get_session()
        headers = self.get_headers()
        node.status = NodeStatus.DOWNLOADING
        node.total_items = len(images)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = 0

        # pages stitched sequentially (each page already fetches tiles concurrently)
        for item in images:
            filename = item.get("filename") or "page.jpg"
            out_path = output_dir / filename
            if out_path.exists() and out_path.stat().st_size > 4096:
                downloaded += 1
                if progress_callback:
                    progress_callback(downloaded, len(images))
                continue
            try:
                ok = await download_zoomify_image(
                    session, item["url"], out_path, headers=headers)
                if ok:
                    downloaded += 1
            except Exception as e:
                logger.warning(f"[tnm] stitch failed {item['url']}: {e}")
            if progress_callback:
                progress_callback(downloaded, len(images))

        node.downloaded_items = downloaded
        node.failed_items = len(images) - downloaded
        node.status = (NodeStatus.COMPLETED if downloaded == len(images)
                       else NodeStatus.DISCOVERED if downloaded else NodeStatus.FAILED)
        return node
