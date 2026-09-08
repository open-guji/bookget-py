# 庆应义塾大学媒体中心数字典藏 (Keio University Digital Collections) Adapter
# https://dcollections.lib.keio.ac.jp/
#
# 漢籍 / 奈良絵本 / 国書 等贵重资料。IIIF Presentation 2.0，但 item 页是 SPA，
# manifest URL 嵌在 item 页的（服务端渲染）HTML 里：
#   .../iiif/{GROUP}/{ID}/manifest.json   (如 KAN/110X-24-1)
# 所以从 item 页抓 manifest URL 再取（无需推导 GROUP 映射）；也支持直接传 manifest URL。
#
# URL patterns:
#   - Item page:     https://dcollections.lib.keio.ac.jp/ja/{collection}/{id}   (如 ja/kanseki/110x-24-1)
#   - IIIF manifest: https://dcollections.lib.keio.ac.jp/sites/default/files/iiif/{GROUP}/{ID}/manifest.json

import re
from typing import Optional

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...logger import logger
from ...exceptions import MetadataExtractionError

# the actual manifest URL (not the page's ?manifest= wrapper)
_MANIFEST_RE = re.compile(
    r'(https?://dcollections\.lib\.keio\.ac\.jp/sites/default/files/iiif/'
    r'[^"\'\s?]+/manifest\.json)')

_NAV = {"about", "news", "content", "search", "sitemap", "user"}


@AdapterRegistry.register
class KeioAdapter(BaseIIIFAdapter):
    """Adapter for Keio University Digital Collections (IIIF, manifest scraped
    from the item page)."""

    site_name = "庆应义塾大学数字典藏 (Keio)"
    site_id = "keio"
    site_domains = ["dcollections.lib.keio.ac.jp"]

    BASE = "https://dcollections.lib.keio.ac.jp"
    default_headers = {"Referer": "https://dcollections.lib.keio.ac.jp/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._manifest_cache: dict[str, str] = {}

    def extract_book_id(self, url: str) -> str:
        # direct manifest URL (also matches the page's ?manifest=… wrapper)
        m = re.search(r'/sites/default/files/iiif/([^/]+/[^/]+)/manifest\.json', url)
        if m:
            return "iiif:" + m.group(1)
        # item page: /ja/{collection}/{id} (or /en/…)
        m = re.search(r'dcollections\.lib\.keio\.ac\.jp/(?:ja|en)/(.+?)/?(?:[?#]|$)', url)
        if m:
            path = m.group(1)
            if path and path.split('/')[0] not in _NAV:
                return "item:" + path
        raise MetadataExtractionError(
            f"Could not extract Keio item id from URL: {url}")

    def get_manifest_url(self, book_id: str) -> str:
        if book_id.startswith("iiif:"):
            return f"{self.BASE}/sites/default/files/iiif/{book_id[5:]}/manifest.json"
        return self._manifest_cache.get(book_id, "")

    async def _resolve_manifest_url(self, book_id: str) -> str:
        if book_id.startswith("iiif:"):
            return self.get_manifest_url(book_id)
        if book_id in self._manifest_cache:
            return self._manifest_cache[book_id]
        item_path = book_id[5:] if book_id.startswith("item:") else book_id
        item_url = f"{self.BASE}/ja/{item_path}"
        session = await self.get_session()
        async with session.get(item_url, headers=self.get_headers(item_url)) as r:
            r.raise_for_status()
            html = await r.text()
        m = _MANIFEST_RE.search(html)
        if not m:
            raise MetadataExtractionError(
                f"No IIIF manifest found on Keio item page: {item_url}")
        self._manifest_cache[book_id] = m.group(1)
        logger.debug(f"[keio] resolved manifest: {m.group(1)}")
        return m.group(1)

    async def get_iiif_manifest(self, book_id: str) -> Optional[dict]:
        url = await self._resolve_manifest_url(book_id)
        session = await self.get_session()
        async with session.get(url, headers=self.get_headers(url)) as r:
            r.raise_for_status()
            return await r.json(content_type=None)
