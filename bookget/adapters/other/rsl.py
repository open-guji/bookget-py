# Российская государственная библиотека (Russian State Library)
# https://viewer.rsl.ru/
#
# The viewer has a clean JSON API, so no scraping:
#   info   https://viewer.rsl.ru/api/v1/document/{id}/info
#   page   https://viewer.rsl.ru/api/v1/document/{id}/page/{n}   (n starts at 1)
#
# NOTE: pages are **1-indexed**. bookget's Go original loops from 0, so its
# first request 404s. Also, most of the collection is in copyright: `info`
# reports isAvailable/accessLevel, and a restricted document answers 403 for
# every page — that is reported up front rather than as 36 failed downloads.

import re
from typing import List, Optional
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...logger import logger
from ...exceptions import MetadataExtractionError

_ID_RE = re.compile(r'(rsl\d{6,})', re.IGNORECASE)
_BASE = "https://viewer.rsl.ru"


@AdapterRegistry.register
class RslAdapter(BaseSiteAdapter):
    """Adapter for the Russian State Library's document viewer."""

    site_name = "俄罗斯国立图书馆 (RSL)"
    site_id = "rsl"
    site_domains = ["viewer.rsl.ru"]

    supports_iiif = False
    supports_images = True
    supports_text = False

    default_headers = {"Referer": f"{_BASE}/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._info: dict = {}

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        match = _ID_RE.search(url)
        if not match:
            raise MetadataExtractionError(
                f"RSL 地址里取不到文档号：{url}\n"
                f"（条目地址形如 viewer.rsl.ru/ru/rsl01000001234）")
        return match.group(1).lower()

    def image_url(self, book_id: str, page: int) -> str:
        return f"{_BASE}/api/v1/document/{book_id}/page/{page}"

    async def _fetch_info(self, book_id: str) -> dict:
        if book_id in self._info:
            return self._info[book_id]

        url = f"{_BASE}/api/v1/document/{book_id}/info"
        session = await self.get_session()
        try:
            async with session.get(url) as response:
                info = await response.json(content_type=None)
        except Exception as e:
            raise MetadataExtractionError(
                f"[rsl] 取文档信息失败：{url}（{e}）") from e

        if not isinstance(info, dict) or info.get("code") == 404:
            raise MetadataExtractionError(
                f"[rsl] 文档不存在：{book_id}"
                f"（接口答复：{(info or {}).get('message', '')[:60]}）")

        self._info[book_id] = info
        return info

    @staticmethod
    def check_access(info: dict):
        """Raise if the document's pages are not downloadable."""
        if info.get("isAvailable"):
            return
        reason = (info.get("accessInformationMessage")
                  or info.get("warningMessage") or "")
        needs_login = info.get("isAuthorizationRequired")
        raise MetadataExtractionError(
            f"[rsl] 该文档不开放下载"
            f"（accessLevel={info.get('accessLevel')}"
            f"{'，需登录' if needs_login else ''}）。"
            f"RSL 大部分馆藏在版权保护期内，取页会一律返回 403。\n"
            f"站点说明：{reason[:120]}")

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        info = await self._fetch_info(book_id)
        description = info.get("description") or {}

        metadata = BookMetadata(
            source_id=book_id,
            source_url=f"{_BASE}/ru/{book_id}",
            source_site=self.site_id,
            index_id=index_id,
        )
        metadata.title = description.get("title") or book_id
        if description.get("author"):
            from ...models.book import Creator
            metadata.creators.append(Creator(name=description["author"]))
        metadata.publisher = description.get("imprint", "")
        metadata.collection_unit = "Российская государственная библиотека"
        metadata.pages = int(info.get("pageCount") or 0)
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        info = await self._fetch_info(book_id)
        self.check_access(info)

        page_count = int(info.get("pageCount") or 0)
        if page_count <= 0:
            raise MetadataExtractionError(
                f"[rsl] 文档 {book_id} 没有可下载的页面（pageCount={page_count}）")

        logger.info(f"RSL {book_id}: {page_count} pages")
        return [
            Resource(
                url=self.image_url(book_id, page),
                resource_type=ResourceType.IMAGE,
                order=page,
                page=str(page),
                filename=f"{book_id}_{page:04d}.jpg",
            )
            # 1-indexed: page 0 answers 404.
            for page in range(1, page_count + 1)
        ]
