# 美国国会图书馆 (Library of Congress) Adapter
# https://www.loc.gov/
#
# 中文善本特藏 (collections/chinese-rare-books)。非 Presentation manifest，但有
# 干净的 JSON API（对齐 bookget app/loc.go）：
#   - 元数据/图片清单：https://www.loc.gov/item/{id}/?fo=json
#       resources[] (卷/册) → files[] (页) → 每页是一组格式变体
#       (image/jpeg 多档 pct:12.5/25/50/100、image/jp2、image/tiff)
#   - 全分辨率图片取 jpeg 的 .../full/pct:100/0/default.jpg
#     （tile.loc.gov/image-services/iiif/…，标准 IIIF Image API）

import asyncio
import re
from pathlib import Path
from typing import Callable, List, Optional

import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...models.manifest import ManifestNode, NodeStatus
from ...logger import logger
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class LOCAdapter(BaseSiteAdapter):
    """Adapter for the Library of Congress (loc.gov) via its fo=json API."""

    site_name = "美国国会图书馆 (Library of Congress)"
    site_id = "loc"
    site_domains = ["loc.gov", "www.loc.gov"]

    supports_iiif = False  # uses LOC JSON API rather than a Presentation manifest
    supports_images = True
    supports_text = False

    BASE = "https://www.loc.gov"
    default_headers = {"Referer": "https://www.loc.gov/"}

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
        m = re.search(r'/item/([A-Za-z0-9]+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract LOC item id from URL: {url}")

    async def _get_item_json(self, book_id: str) -> dict:
        session = await self.get_session()
        url = f"{self.BASE}/item/{book_id}/?fo=json"
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        data = await self._get_item_json(book_id)
        item = data.get("item", {})
        meta = BookMetadata(
            source_id=book_id,
            source_url=f"{self.BASE}/item/{book_id}/",
            source_site=self.site_id,
            index_id=index_id,
            collection_unit="美国国会图书馆 (Library of Congress)",
        )
        title = item.get("title", "")
        meta.title = title[0] if isinstance(title, list) else title
        for c in (item.get("contributors") or []):
            name = c if isinstance(c, str) else (c.get("title") if isinstance(c, dict) else "")
            if name:
                meta.creators.append(Creator(name=name))
        date = item.get("date", "")
        meta.date = date[0] if isinstance(date, list) else date
        langs = item.get("language") or []
        if langs:
            meta.language = langs[0] if isinstance(langs, list) else langs
        return meta

    @staticmethod
    def _best_jpeg(formats: list) -> Optional[str]:
        """Pick the full-resolution IIIF jpeg from a page's format list."""
        jpegs = [
            f["url"] for f in formats
            if isinstance(f, dict) and f.get("mimetype") == "image/jpeg"
            and isinstance(f.get("url"), str) and "/full/" in f["url"]
        ]
        if not jpegs:
            return None

        def pct(u: str) -> float:
            m = re.search(r'/pct:([\d.]+)/', u)
            return float(m.group(1)) if m else 0.0
        return max(jpegs, key=pct)

    async def get_image_list(self, book_id: str) -> List[Resource]:
        data = await self._get_item_json(book_id)
        resources = data.get("resources") or []
        out: List[Resource] = []
        multi_vol = len(resources) > 1
        order = 0
        for vi, res in enumerate(resources, 1):
            pages = res.get("files") or []
            for pi, page in enumerate(pages, 1):
                if not isinstance(page, list):
                    continue
                url = self._best_jpeg(page)
                if not url:
                    continue
                order += 1
                fname = (f"v{vi:02d}_{pi:04d}.jpg" if multi_vol
                         else f"{order:04d}.jpg")
                out.append(Resource(
                    url=url,
                    resource_type=ResourceType.IMAGE,
                    order=order,
                    volume=str(vi) if multi_vol else "",
                    page=str(pi),
                    filename=fname,
                ))
        logger.info(
            f"[loc] {book_id}: {len(out)} pages across {len(resources)} resource(s)")
        return out

    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """Download a volume node's images (direct IIIF jpegs, no auth)."""
        images = node.source_data.get("images")
        if not images:
            urls = node.source_data.get("image_urls", [])
            images = [{"url": u, "filename": f"{i + 1:04d}.jpg"}
                      for i, u in enumerate(urls)]
        if not images:
            logger.warning(f"[loc] node {node.id} has no images")
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
                        return
                    out_path.write_bytes(content)
                    downloaded += 1
                    if progress_callback:
                        progress_callback(downloaded, len(images))
                except Exception as e:
                    logger.warning(f"[loc] failed {url}: {e}")

        await asyncio.gather(*[fetch_one(it) for it in images])
        node.downloaded_items = downloaded
        node.failed_items = len(images) - downloaded
        node.status = (NodeStatus.COMPLETED if downloaded == len(images)
                       else NodeStatus.DISCOVERED if downloaded else NodeStatus.FAILED)
        return node
