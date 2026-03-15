# Harvard University Library Adapter
# https://curiosity.lib.harvard.edu/chinese-rare-books

import re
from typing import List, Optional
import aiohttp

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Creator
from ...logger import logger


@AdapterRegistry.register
class HarvardAdapter(BaseIIIFAdapter):
    """
    Adapter for Harvard University Library - Chinese Rare Books.
    
    Harvard uses CURIOSity platform (Blacklight) with IIIF support.
    The platform provides JSON API by appending .json to URLs.
    
    URL patterns:
    - Detail page: /chinese-rare-books/catalog/{collection_prefix}-{HOLLIS_id}
    - JSON API: /chinese-rare-books/catalog/{id}.json
    - IIIF Manifest: https://nrs.harvard.edu/urn-3:FHCL:{NRS_ID}:MANIFEST
    """
    
    site_name = "哈佛大学图书馆 (Harvard)"
    site_id = "harvard"
    site_domains = [
        "curiosity.lib.harvard.edu",
        "iiif.lib.harvard.edu",
        "listview.lib.harvard.edu"
    ]
    
    supports_iiif = True
    supports_text = False
    
    BASE_URL = "https://curiosity.lib.harvard.edu"
    
    def __init__(self, config=None):
        super().__init__(config)
        self._manifest_urls = {}  # Cache manifest URLs
    
    def extract_book_id(self, url: str) -> str:
        """
        Extract book ID from Harvard URL.
        
        Patterns:
        - /catalog/49-990080724750203941
        - /manifests/view/drs:53262215
        """
        # Try catalog ID pattern
        match = re.search(r'/catalog/(\d+-\d+)', url)
        if match:
            return match.group(1)
        
        # Try DRS ID pattern (from manifest viewer)
        match = re.search(r'manifests/view/(drs:[0-9]+)', url)
        if match:
            # For DRS IDs, we need to look up the catalog ID
            return match.group(1)
        
        # Try manifest URL pattern
        match = re.search(r'/manifests/([A-Za-z0-9:_-]+)', url)
        if match:
            return match.group(1)
        
        raise ValueError(f"Could not extract book ID from URL: {url}")
    
    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Fetch metadata from Blacklight JSON API."""
        session = await self.get_session()
        
        # If book_id is a DRS ID, just use IIIF manifest
        if book_id.startswith("drs:"):
            return await super().get_metadata(book_id)
        
        # Otherwise use Blacklight JSON API for richer metadata
        url = f"{self.BASE_URL}/chinese-rare-books/catalog/{book_id}.json"
        
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                return self._parse_blacklight_metadata(data, book_id)
        except Exception as e:
            logger.warning(f"Blacklight API failed, falling back to IIIF: {e}")
            return await super().get_metadata(book_id)
    
    def _parse_blacklight_metadata(self, data: dict, book_id: str) -> BookMetadata:
        """Parse Blacklight JSON response."""
        metadata = BookMetadata(source_id=book_id)
        
        attrs = data.get("data", {}).get("attributes", {})
        
        # Title
        metadata.title = attrs.get("title", "")
        
        # Parse each attribute
        for key, value in attrs.items():
            if not isinstance(value, dict):
                continue
            
            attr_value = value.get("attributes", {}).get("value", "")
            label = value.get("attributes", {}).get("label", "")
            
            if "creator-contributor" in key:
                # Parse creator string (may contain HTML breaks)
                creators = attr_value.replace("<br />", "|").split("|")
                for c in creators:
                    c = c.strip()
                    if c:
                        metadata.creators.append(Creator(name=c))
            elif "date" in key:
                metadata.date = attr_value
            elif "publisher" in key:
                metadata.publisher = attr_value
            elif "place-of-origin" in key:
                metadata.place = attr_value
            elif "language" in key:
                metadata.language = attr_value
            elif "extent" in key:
                metadata.volume_info = attr_value
            elif "repository" in key:
                metadata.collection_unit = attr_value
            elif "note" in key:
                metadata.notes.append(attr_value)
            elif "subjects" in key:
                if isinstance(attr_value, list):
                    metadata.subjects.extend(attr_value)
                else:
                    metadata.subjects.append(attr_value)
        
        # Store raw data
        metadata.raw_metadata = data
        
        return metadata
    
    def get_manifest_url(self, book_id: str) -> str:
        """Construct IIIF manifest URL."""
        if book_id in self._manifest_urls:
            return self._manifest_urls[book_id]
        
        # For DRS IDs
        if book_id.startswith("drs:"):
            return f"https://iiif.lib.harvard.edu/manifests/{book_id}"
        
        # For IDS IDs
        if book_id.startswith("ids:"):
            return f"https://iiif.lib.harvard.edu/manifests/{book_id}"
        
        # For catalog IDs, we need to extract from page or construct
        # This is a simplified version - full implementation would scrape the page
        return f"https://iiif.lib.harvard.edu/manifests/drs:{book_id}"
    
    async def get_image_list(self, book_id: str) -> list:
        """Get images, attempting to find manifest URL first."""
        session = await self.get_session()
        
        # Try to get manifest URL from catalog page
        if not book_id.startswith("drs:") and book_id not in self._manifest_urls:
            url = f"{self.BASE_URL}/chinese-rare-books/catalog/{book_id}"
            try:
                async with session.get(url) as response:
                    html = await response.text()
                    # Extract manifest URL from page
                    match = re.search(r"copyManifestToClipBoard\('([^']+)'\)", html)
                    if match:
                        self._manifest_urls[book_id] = match.group(1)
            except Exception as e:
                logger.warning(f"Could not extract manifest URL: {e}")
        
        return await super().get_image_list(book_id)
