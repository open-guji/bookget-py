# 国立国会図書館 (NDL) Adapter
# https://dl.ndl.go.jp/

import re
from typing import List, Optional
import aiohttp

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...logger import logger
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class NDLAdapter(BaseIIIFAdapter):
    """
    Adapter for 国立国会図書館デジタルコレクション (NDL Digital Collections).
    
    Japan's National Diet Library - one of the largest digital libraries in Japan.
    Supports IIIF v2 with custom metadata API.
    
    URL patterns:
    - Detail page: https://dl.ndl.go.jp/pid/{book_id}
    - With page: https://dl.ndl.go.jp/pid/{book_id}/{volume}/{page}
    - IIIF Manifest: https://dl.ndl.go.jp/api/iiif/{book_id}/manifest.json
    - Item API: https://dl.ndl.go.jp/api/item/search/info:ndljp/pid/{book_id}
    """
    
    site_name = "国立国会図書館 (NDL)"
    site_id = "ndl"
    site_domains = ["dl.ndl.go.jp"]
    
    supports_iiif = True
    supports_text = False  # OCR text available but not easily extractable
    
    BASE_URL = "https://dl.ndl.go.jp"
    
    manifest_url_template = "https://dl.ndl.go.jp/api/iiif/{book_id}/manifest.json"
    
    def extract_book_id(self, url: str) -> str:
        """
        Extract PID from NDL URL.
        
        Patterns:
        - /pid/2592420
        - /pid/2592420/1/1
        - /info:ndljp/pid/2592420
        """
        # Try /pid/{id} pattern
        match = re.search(r'/pid/(\d+)', url)
        if match:
            return match.group(1)
        
        # Try info:ndljp/pid/{id} pattern
        match = re.search(r'info:ndljp/pid/(\d+)', url)
        if match:
            return match.group(1)
        
        raise MetadataExtractionError(f"Could not extract book ID from URL: {url}")
    
    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """
        Fetch metadata from NDL Item API.
        
        The Item API provides richer metadata than the IIIF manifest.
        """
        session = await self.get_session()
        url = f"{self.BASE_URL}/api/item/search/info:ndljp/pid/{book_id}"
        
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                return self._parse_item_metadata(data, book_id)
        except Exception as e:
            logger.warning(f"Item API failed, falling back to IIIF: {e}")
            return await super().get_metadata(book_id)
    
    def _parse_item_metadata(self, data: dict, book_id: str) -> BookMetadata:
        """Parse NDL Item API response."""
        metadata = BookMetadata(
            source_id=book_id,
            iiif_manifest_url=self.get_manifest_url(book_id)
        )
        
        item = data.get("item", {})
        meta = item.get("meta", {})
        
        # PID
        metadata.source_id = item.get("itemId", book_id)
        
        # Title - stored in various meta fields
        # 0311Dtct is title in katakana, we need the original
        title_fields = ["0200Dod", "0101Dod", "0042Dtct"]
        for field in title_fields:
            if field in meta:
                values = meta[field]
                if values:
                    metadata.title = values[0] if isinstance(values, list) else values
                    break
        
        # Creators - in 0010Dtct
        creators = meta.get("0010Dtct", [])
        if isinstance(creators, list):
            for c in creators:
                if c:
                    metadata.creators.append(Creator(name=c))
        
        # Publication info - in 0058Dod
        pub_info = meta.get("0058Dod", [])
        if pub_info:
            metadata.date = pub_info[0] if isinstance(pub_info, list) else pub_info
        
        # Language - in 0065Dk
        lang = meta.get("0065Dk", [])
        if lang:
            metadata.language = lang[0] if isinstance(lang, list) else lang
        
        # Resource types - in 0078Dk
        types = meta.get("0078Dk", [])
        if types:
            metadata.doc_type = ", ".join(types) if isinstance(types, list) else types
        
        # Rights info
        rights = item.get("rights", {})
        metadata.rights = rights.get("code", "")
        
        # Store raw
        metadata.raw_metadata = data
        
        return metadata
    
    async def get_image_list(self, book_id: str) -> List[Resource]:
        """
        Get images from IIIF manifest.
        
        NDL may have multiple volumes, so we check the TOC API first.
        """
        session = await self.get_session()
        
        # Check for multi-volume structure
        toc_url = f"{self.BASE_URL}/api/meta/search/toc/facet/{book_id}"
        
        try:
            async with session.get(toc_url) as response:
                if response.status == 200:
                    toc_data = await response.json()
                    children = toc_data.get("children", [])
                    
                    if children:
                        # Multi-volume: get images from each volume
                        all_resources = []
                        for idx, child in enumerate(children):
                            volume_id = child.get("id", "")
                            if volume_id:
                                vol_resources = await self._get_volume_images(volume_id, idx + 1)
                                all_resources.extend(vol_resources)
                        return all_resources
        except Exception as e:
            logger.debug(f"TOC API check failed: {e}")
        
        # Single volume or TOC failed - use standard IIIF
        return await super().get_image_list(book_id)
    
    async def _get_volume_images(self, volume_id: str, volume_num: int) -> List[Resource]:
        """Get images for a specific volume."""
        resources = await super().get_image_list(volume_id)
        
        # Add volume info to resources
        for r in resources:
            r.volume = str(volume_num)
            r.filename = f"v{volume_num:02d}_{r.order:04d}.jpg"
        
        return resources
