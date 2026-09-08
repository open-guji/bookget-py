# 香港科技大学图书馆 (HKUST Library) Adapter
# https://lbezone.hkust.edu.hk/
#
# 古籍與特藏（線裝書、古地圖、清末民初線裝書等）。非 IIIF：詳情頁 (/bib/{id})
# 內嵌一個 BookReader，其圖片走自有 API。流程（對齊 bookget app/usthk.go）：
#   1. GET /bib/{id} → 從 HTML 抓 sPath（view_book('…') / view.php?obj=…），如 "10/o/b334647/ebook"
#   2. GET /bookreader/getfilelist.php?path={sPath} → JSON {"file_list":["pg00001.jpg", …]}
#   3. 圖片 URL：https://lbezone.hkust.edu.hk/obj/{sPath}/{filename}

import asyncio
import re
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import quote

import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...models.manifest import ManifestNode, NodeStatus
from ...logger import logger
from ...exceptions import MetadataExtractionError

_SPATH_RE = re.compile(r'''view_book\(["']([^"']+)["']''')
_SPATH_RE2 = re.compile(r'''view\.php\?obj=([^&"'\s\\]+)''')
_TITLE_RE = re.compile(r'<title>([^<]+)</title>', re.IGNORECASE)


@AdapterRegistry.register
class HKUSTAdapter(BaseSiteAdapter):
    """Adapter for the HKUST Library rare-books reader (lbezone.hkust.edu.hk)."""

    site_name = "香港科技大学图书馆 (HKUST)"
    site_id = "hkust"
    site_domains = ["lbezone.hkust.edu.hk"]

    supports_iiif = False
    supports_images = True
    supports_text = False

    BASE = "https://lbezone.hkust.edu.hk"
    default_headers = {"Referer": "https://lbezone.hkust.edu.hk/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._spath_cache: dict[str, str] = {}

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        m = re.search(r'/bib/([A-Za-z0-9_-]+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract HKUST bib id from URL: {url}")

    async def _fetch_bib_page(self, book_id: str) -> str:
        session = await self.get_session()
        url = f"{self.BASE}/bib/{book_id}"
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.text(errors="ignore")

    async def _get_spath(self, book_id: str, html: str = None) -> str:
        """Extract the BookReader storage path (sPath) for a bib id."""
        if book_id in self._spath_cache:
            return self._spath_cache[book_id]
        if html is None:
            html = await self._fetch_bib_page(book_id)
        m = _SPATH_RE.search(html) or _SPATH_RE2.search(html)
        if not m:
            raise MetadataExtractionError(
                f"No BookReader sPath found on bib page: {book_id}")
        spath = m.group(1)
        self._spath_cache[book_id] = spath
        return spath

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        html = await self._fetch_bib_page(book_id)
        meta = BookMetadata(
            source_id=book_id,
            source_url=f"{self.BASE}/bib/{book_id}",
            source_site=self.site_id,
            index_id=index_id,
            collection_unit="香港科技大學圖書館",
        )
        tm = _TITLE_RE.search(html)
        if tm:
            title = re.sub(r'\s*[-|–]\s*(HKUST|香港科技大學).*$', '', tm.group(1))
            meta.title = title.strip()
        # cache sPath opportunistically
        try:
            await self._get_spath(book_id, html)
        except MetadataExtractionError:
            pass
        return meta

    async def _get_file_list(self, spath: str) -> List[str]:
        session = await self.get_session()
        api = f"{self.BASE}/bookreader/getfilelist.php?path={quote(spath)}"
        async with session.get(api) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
        files = data.get("file_list") or data.get("FileList") or []
        return [f for f in files if f]

    async def get_image_list(self, book_id: str) -> List[Resource]:
        spath = await self._get_spath(book_id)
        files = await self._get_file_list(spath)
        resources: List[Resource] = []
        for i, fname in enumerate(files, 1):
            resources.append(Resource(
                url=f"{self.BASE}/obj/{spath}/{fname}",
                resource_type=ResourceType.IMAGE,
                order=i,
                page=str(i),
                filename=f"{i:04d}{Path(fname).suffix or '.jpg'}",
            ))
        logger.info(f"[hkust] {book_id}: {len(resources)} pages")
        return resources

    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """Download all images for a volume node (direct JPEGs, no auth)."""
        images = node.source_data.get("images")
        if not images:
            urls = node.source_data.get("image_urls", [])
            images = [{"url": u, "filename": f"{i + 1:04d}.jpg"}
                      for i, u in enumerate(urls)]
        if not images:
            logger.warning(f"[hkust] node {node.id} has no images")
            node.status = NodeStatus.FAILED
            return node

        node.status = NodeStatus.DOWNLOADING
        node.total_items = len(images)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        session = await self.get_session()
        headers = self.get_headers()
        concurrency, min_size = 4, 1024
        if self.config and hasattr(self.config, "download"):
            concurrency = max(1, self.config.download.concurrent_downloads)
            min_size = self.config.download.min_image_size
        semaphore = asyncio.Semaphore(concurrency)
        downloaded = 0

        async def fetch_one(item: dict):
            nonlocal downloaded
            url = item["url"]
            filename = item.get("filename") or url.rsplit("/", 1)[-1]
            out_path = output_dir / filename
            if out_path.exists() and out_path.stat().st_size >= min_size:
                downloaded += 1
                if progress_callback:
                    progress_callback(downloaded, len(images))
                return
            async with semaphore:
                try:
                    async with session.get(url, headers=headers) as resp:
                        resp.raise_for_status()
                        content = await resp.read()
                    if len(content) < min_size:
                        logger.warning(f"[hkust] image too small: {filename}")
                        return
                    out_path.write_bytes(content)
                    downloaded += 1
                    if progress_callback:
                        progress_callback(downloaded, len(images))
                except Exception as e:
                    logger.warning(f"[hkust] failed {url}: {e}")

        await asyncio.gather(*[fetch_one(it) for it in images])
        node.downloaded_items = downloaded
        node.failed_items = len(images) - downloaded
        node.status = (NodeStatus.COMPLETED if downloaded == len(images)
                       else NodeStatus.DISCOVERED if downloaded else NodeStatus.FAILED)
        return node
