# Princeton University Library Adapter
# https://dpul.princeton.edu/eastasian

import re
from typing import List, Optional
import aiohttp

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Creator
from ...logger import logger


@AdapterRegistry.register
class PrincetonAdapter(BaseIIIFAdapter):
    """
    Adapter for Princeton University Library - East Asian Library.
    
    Home to the Gest Collection, one of the most important Chinese 
    rare book collections in North America.
    
    Uses Figgy/DPUL platform with IIIF support.
    
    URL patterns:
    - Catalog: https://dpul.princeton.edu/eastasian/catalog/{id}
    - IIIF Manifest: https://figgy.princeton.edu/concern/scanned_resources/{id}/manifest
    """
    
    site_name = "普林斯顿大学图书馆 (Princeton)"
    site_id = "princeton"
    site_domains = [
        "dpul.princeton.edu",
        "figgy.princeton.edu"
    ]
    
    supports_iiif = True
    supports_text = False
    
    def extract_book_id(self, url: str) -> str:
        """Extract resource ID from Princeton URL."""
        # Try catalog pattern
        match = re.search(r'/catalog/([a-zA-Z0-9-]+)', url)
        if match:
            return match.group(1)
        
        # Try figgy pattern
        match = re.search(r'/scanned_resources/([a-zA-Z0-9-]+)', url)
        if match:
            return match.group(1)
        
        # Try manifest URL pattern
        match = re.search(r'/([a-zA-Z0-9-]+)/manifest', url)
        if match:
            return match.group(1)
        
        raise ValueError(f"Could not extract book ID from URL: {url}")
    
    def get_manifest_url(self, book_id: str) -> str:
        """Construct IIIF manifest URL."""
        return f"https://figgy.princeton.edu/concern/scanned_resources/{book_id}/manifest"
    
    def _parse_manifest_metadata(self, manifest: dict, book_id: str) -> BookMetadata:
        """Parse Princeton IIIF manifest metadata."""
        metadata = super()._parse_manifest_metadata(manifest, book_id)
        
        # Princeton manifests may have additional structured metadata
        for item in manifest.get("metadata", []):
            label = self._extract_label(item.get("label", ""))
            value = self._extract_label(item.get("value", ""))
            
            label_lower = label.lower()
            
            if "call number" in label_lower:
                metadata.call_number = value
            elif "extent" in label_lower:
                metadata.volume_info = value
            elif "collection" in label_lower:
                metadata.collection_unit = value
        
        return metadata
