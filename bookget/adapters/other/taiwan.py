# Taiwan Library Adapters

import re
from typing import List
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...logger import logger
from ...exceptions import MetadataExtractionError


# NCL Taiwan rbook 適配器已搬到 other/ncl_rbook.py（新版 NCLSearch URL +
# Playwright headed + 私有 token chain）。舊的 IIIF 假設不成立（rbook.ncl.edu.tw
# 沒有 IIIF endpoint），故刪除。


@AdapterRegistry.register
class PalaceMuseumTaipeiAdapter(BaseSiteAdapter):
    """
    Adapter for 國立故宮博物院 (National Palace Museum, Taipei).
    
    Houses treasures from the Forbidden City including rare manuscripts.
    Uses custom API (not IIIF).
    
    URL patterns:
    - Detail: https://digitalarchive.npm.gov.tw/Painting/Content?pid={id}
    """

    site_name = "臺灣故宮博物院 (NPM Taipei)"
    site_id = "npm_taipei"
    site_domains = ["digitalarchive.npm.gov.tw"]

    supports_iiif = False
    supports_text = False

    def __init__(self, config=None):
        super().__init__(config)
        self._session = None

    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def extract_book_id(self, url: str) -> str:
        """Extract painting/book ID from NPM URL."""
        match = re.search(r'[?&]pid=([^&]+)', url)
        if match:
            return match.group(1)

        raise MetadataExtractionError(f"Could not extract ID from URL: {url}")

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Fetch metadata from NPM API."""
        session = await self.get_session()
        url = f"https://digitalarchive.npm.gov.tw/api/Painting/{book_id}"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return BookMetadata(source_id=book_id)

                data = await response.json()
                return self._parse_metadata(data, book_id)
        except Exception as e:
            logger.warning(f"Failed to fetch NPM metadata: {e}")
            return BookMetadata(source_id=book_id)

    def _parse_metadata(self, data: dict, book_id: str) -> BookMetadata:
        """Parse NPM API response."""
        metadata = BookMetadata(source_id=book_id)

        metadata.title = data.get("title", "")
        metadata.dynasty = data.get("dynasty", "")

        author = data.get("author", "")
        if author:
            metadata.creators.append(Creator(name=author))

        metadata.dimensions = data.get("size", "")
        metadata.doc_type = data.get("category", "")
        metadata.collection_unit = "國立故宮博物院"

        metadata.raw_metadata = data
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Get image list from NPM."""
        session = await self.get_session()
        url = f"https://digitalarchive.npm.gov.tw/api/Painting/{book_id}/images"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                resources = []

                for idx, img in enumerate(data.get("images", [])):
                    resource = Resource(
                        url=img.get("url", ""),
                        resource_type=ResourceType.IMAGE,
                        order=idx + 1,
                    )
                    resources.append(resource)

                return resources
        except Exception as e:
            logger.warning(f"Failed to get NPM images: {e}")
            return []

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
