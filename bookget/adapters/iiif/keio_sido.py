# 庆应义塾大学斯道文庫 漢籍善本 (Keio University, Shido Bunko)
# https://db2.sido.keio.ac.jp/kanseki/
#
# IIIF Presentation 2.0. The item page does not expose a derivable manifest
# path, but it prints the manifest URL into its HTML, so it is scraped the
# same way as the dcollections Keio adapter and khirin.
#
# URL patterns:
#   - Item page:     https://db2.sido.keio.ac.jp/kanseki/bib_frame?id=006754
#   - Image page:    https://db2.sido.keio.ac.jp/kanseki/bib_image?id=006754
#   - IIIF manifest: https://db2.sido.keio.ac.jp/iiif/manifests/kanseki/
#                    {id}/{id}-{folio}/manifest.json

import re
from typing import Optional

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...logger import logger
from ...exceptions import MetadataExtractionError

_MANIFEST_RE = re.compile(
    r'(https?://db2\.sido\.keio\.ac\.jp/iiif/manifests/[^"\'\s?]+/manifest\.json)')
_ID_RE = re.compile(r'\bid=([A-Za-z0-9_-]+)')
_MANIFEST_PATH_RE = re.compile(
    r'/iiif/manifests/kanseki/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)/manifest\.json')

_BASE = "https://db2.sido.keio.ac.jp"


@AdapterRegistry.register
class KeioSidoAdapter(BaseIIIFAdapter):
    """Adapter for Keio University's Shido Bunko Chinese rare books."""

    site_name = "庆应义塾大学斯道文庫 漢籍 (Keio Shido)"
    site_id = "keio_sido"
    site_domains = ["db2.sido.keio.ac.jp"]

    BASE = _BASE
    default_headers = {"Referer": "https://db2.sido.keio.ac.jp/kanseki/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._manifest_cache: dict = {}

    def extract_book_id(self, url: str) -> str:
        # A manifest URL carries both the record id and the folio.
        direct = _MANIFEST_PATH_RE.search(url)
        if direct:
            book_id = direct.group(1)
            self._manifest_cache[book_id] = (
                f"{_BASE}/iiif/manifests/kanseki/"
                f"{direct.group(1)}/{direct.group(2)}/manifest.json")
            return book_id

        # bib_frame?id=… / bib_image?id=…
        match = _ID_RE.search(url)
        if match:
            return match.group(1)

        raise MetadataExtractionError(
            f"斯道文庫地址里没有 id 参数：{url}\n"
            f"（条目地址形如 kanseki/bib_frame?id=006754）")

    def get_manifest_url(self, book_id: str) -> str:
        return self._manifest_cache.get(book_id, "")

    async def _resolve_manifest_url(self, book_id: str) -> str:
        if book_id in self._manifest_cache:
            return self._manifest_cache[book_id]

        page_url = f"{_BASE}/kanseki/bib_image?id={book_id}"
        session = await self.get_session()
        try:
            async with session.get(
                    page_url, headers=self.get_headers(page_url)) as response:
                # The site answers 400 (not 404) for an id it does not know,
                # which otherwise surfaced as a bare ClientResponseError.
                response.raise_for_status()
                html = await response.text()
        except MetadataExtractionError:
            raise
        except Exception as e:
            raise MetadataExtractionError(
                f"[keio_sido] 取条目页失败：{page_url}（{e}）\n"
                f"（id 可能不存在——站点对未知 id 回 400 而非 404）") from e

        found = sorted(set(_MANIFEST_RE.findall(html)))
        if not found:
            raise MetadataExtractionError(
                f"[keio_sido] 该条目没有 IIIF manifest：{page_url}\n"
                f"（斯道文庫库里有相当一部分书志记录尚未数字化影像）")
        if len(found) > 1:
            # Not observed in the wild, but say so rather than silently
            # downloading only the first fascicle.
            logger.warning(
                f"[keio_sido] {book_id} 有 {len(found)} 个 manifest，本次只取第一个；"
                f"其余可直接传 manifest URL 下载：{found[1:]}")

        self._manifest_cache[book_id] = found[0]
        logger.debug(f"[keio_sido] resolved manifest: {found[0]}")
        return found[0]

    async def get_iiif_manifest(self, book_id: str) -> Optional[dict]:
        url = await self._resolve_manifest_url(book_id)
        session = await self.get_session()
        async with session.get(url, headers=self.get_headers(url)) as response:
            response.raise_for_status()
            return await response.json(content_type=None)
