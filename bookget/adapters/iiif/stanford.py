# Stanford University Library Adapter
# https://searchworks.stanford.edu/

import re
from typing import List, Optional
import aiohttp

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata
from ...logger import logger


@AdapterRegistry.register 
class StanfordAdapter(BaseIIIFAdapter):
    """
    Adapter for Stanford University Libraries.
    
    Stanford is one of the founding members of the IIIF consortium.
    Uses PURL (Persistent URL) system for digital resources.
    
    URL patterns:
    - SearchWorks: https://searchworks.stanford.edu/view/{druid}
    - PURL: https://purl.stanford.edu/{druid}
    - IIIF Manifest: https://purl.stanford.edu/{druid}/iiif/manifest
    """
    
    site_name = "斯坦福大学图书馆 (Stanford)"
    site_id = "stanford"
    site_domains = [
        "searchworks.stanford.edu",
        "purl.stanford.edu",
        "stacks.stanford.edu"
    ]
    
    supports_iiif = True
    supports_text = False
    
    def extract_book_id(self, url: str) -> str:
        """Extract DRUID from Stanford URL."""
        # DRUID pattern: two letters followed by numbers and letters
        # e.g., bb123cd4567
        match = re.search(r'([a-z]{2}\d{3}[a-z]{2}\d{4})', url.lower())
        if match:
            return match.group(1)
        
        # Try /view/ pattern
        match = re.search(r'/view/([^/]+)', url)
        if match:
            return match.group(1)
        
        raise ValueError(f"Could not extract DRUID from URL: {url}")
    
    def get_manifest_url(self, book_id: str) -> str:
        """Construct IIIF manifest URL."""
        return f"https://purl.stanford.edu/{book_id}/iiif/manifest"


@AdapterRegistry.register
class BerkeleyAdapter(BaseIIIFAdapter):
    """
    Adapter for UC Berkeley East Asian Library.
    
    One of the largest collections of Song and Yuan dynasty 
    woodblock prints outside of Asia.
    
    URL patterns:
    - Digital Collections: https://digicoll.lib.berkeley.edu/record/{id}
    - IIIF Manifest: varies by collection
    """
    
    site_name = "柏克莱加州大学东亚图书馆 (Berkeley)"
    site_id = "berkeley"
    site_domains = ["digicoll.lib.berkeley.edu"]
    
    supports_iiif = True
    supports_text = False
    
    def extract_book_id(self, url: str) -> str:
        """Extract record ID from Berkeley URL."""
        match = re.search(r'/record/(\d+)', url)
        if match:
            return match.group(1)
        
        raise ValueError(f"Could not extract record ID from URL: {url}")
    
    def get_manifest_url(self, book_id: str) -> str:
        """Construct IIIF manifest URL."""
        # Berkeley uses different manifest URL patterns
        return f"https://digicoll.lib.berkeley.edu/iiif/{book_id}/manifest.json"
