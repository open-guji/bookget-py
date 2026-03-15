# Base IIIF Adapter - Handles IIIF-compatible digital libraries

import re
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, urljoin
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...logger import logger
from ...exceptions import MetadataExtractionError


class BaseIIIFAdapter(BaseSiteAdapter):
    """
    Base adapter for IIIF-compatible digital libraries.
    
    This adapter can be subclassed for specific IIIF sites that require
    custom manifest URL construction or metadata extraction.
    
    IIIF Presentation API 2.0 reference:
    https://iiif.io/api/presentation/2.1/
    """
    
    supports_iiif = True
    supports_images = True
    supports_text = False  # Most IIIF sites don't provide text
    
    # Subclasses should override these
    manifest_url_template: str = ""  # e.g., "https://example.com/iiif/{book_id}/manifest.json"
    
    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    def get_manifest_url(self, book_id: str) -> str:
        """
        Construct IIIF manifest URL from book ID.
        Override in subclasses for site-specific URL patterns.
        """
        if self.manifest_url_template:
            return self.manifest_url_template.format(book_id=book_id)
        raise NotImplementedError("Subclass must implement get_manifest_url or set manifest_url_template")
    
    async def get_iiif_manifest(self, book_id: str) -> Optional[dict]:
        """Fetch and parse IIIF manifest."""
        url = self.get_manifest_url(book_id)
        session = await self.get_session()
        headers = self.get_headers(url)
        
        try:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            logger.error(f"Failed to fetch manifest: {e}")
            raise MetadataExtractionError(f"Failed to fetch IIIF manifest: {e}")
    
    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Extract metadata from IIIF manifest."""
        manifest = await self.get_iiif_manifest(book_id)
        return self._parse_manifest_metadata(manifest, book_id)
    
    def _parse_manifest_metadata(self, manifest: dict, book_id: str) -> BookMetadata:
        """
        Parse metadata from IIIF manifest.
        Override in subclasses for site-specific parsing.
        """
        metadata = BookMetadata(
            source_id=book_id,
            iiif_manifest_url=self.get_manifest_url(book_id),
        )
        
        # Parse label (title)
        metadata.title = self._extract_label(manifest.get("label", ""))
        
        # Parse metadata array
        for item in manifest.get("metadata", []):
            label = self._extract_label(item.get("label", ""))
            value = self._extract_label(item.get("value", ""))
            
            label_lower = label.lower()
            
            if "title" in label_lower:
                if not metadata.title:
                    metadata.title = value
            elif "creator" in label_lower or "author" in label_lower or "著" in label:
                metadata.creators.append(Creator(name=value))
            elif "date" in label_lower or "年" in label:
                metadata.date = value
            elif "publisher" in label_lower:
                metadata.publisher = value
            elif "language" in label_lower:
                metadata.language = value
            elif "rights" in label_lower or "license" in label_lower:
                metadata.rights = value
            elif "description" in label_lower:
                metadata.notes.append(value)
        
        # Store raw metadata
        metadata.raw_metadata = manifest
        
        return metadata
    
    def _extract_label(self, value: Any) -> str:
        """
        Extract string from IIIF label/value which can be:
        - Simple string
        - Array of strings
        - Object with language keys
        """
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            # Take first non-empty value
            for v in value:
                if isinstance(v, str) and v:
                    return v
                if isinstance(v, dict):
                    # Language map like {"@value": "text", "@language": "en"}
                    if "@value" in v:
                        return v["@value"]
            return str(value[0]) if value else ""
        if isinstance(value, dict):
            # Language map
            if "@value" in value:
                return value["@value"]
            # Try common language keys
            for lang in ["zh", "en", "ja", "und"]:
                if lang in value:
                    return value[lang]
            # Return first value
            return str(next(iter(value.values()), ""))
        return str(value) if value else ""
    
    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Extract image resources from IIIF manifest."""
        manifest = await self.get_iiif_manifest(book_id)
        return self._parse_manifest_images(manifest)
    
    def _parse_manifest_images(self, manifest: dict) -> List[Resource]:
        """
        Parse image resources from IIIF manifest.
        
        Follows IIIF Presentation API 2.0 structure:
        manifest -> sequences[0] -> canvases[] -> images[0] -> resource
        """
        resources = []
        
        sequences = manifest.get("sequences", [])
        if not sequences:
            logger.warning("No sequences found in manifest")
            return resources
        
        canvases = sequences[0].get("canvases", [])
        
        for idx, canvas in enumerate(canvases):
            # Get canvas label for page info
            page_label = self._extract_label(canvas.get("label", ""))
            
            # Get image from canvas
            images = canvas.get("images", [])
            if not images:
                continue
            
            image_annotation = images[0]
            resource_data = image_annotation.get("resource", {})
            
            # Get image URL
            image_url = resource_data.get("@id", "")
            
            # Get IIIF Image API service ID for full quality
            service = resource_data.get("service", {})
            if isinstance(service, list):
                service = service[0] if service else {}
            
            service_id = service.get("@id", "")
            
            # Get dimensions
            width = resource_data.get("width", canvas.get("width", 0))
            height = resource_data.get("height", canvas.get("height", 0))
            
            # Construct full-quality image URL if we have service ID
            if service_id:
                # IIIF Image API 2.0: {service_id}/full/full/0/default.jpg
                image_url = f"{service_id}/full/full/0/default.jpg"
            
            resource = Resource(
                url=image_url,
                resource_type=ResourceType.IMAGE,
                order=idx + 1,
                page=page_label or str(idx + 1),
                iiif_service_id=service_id,
                width=width,
                height=height,
            )
            resources.append(resource)
        
        return resources
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


# Example: Generic IIIF adapter that can handle any IIIF manifest URL
@AdapterRegistry.register
class GenericIIIFAdapter(BaseIIIFAdapter):
    """
    Generic adapter for any IIIF manifest URL.
    
    Handles URLs that directly point to IIIF manifests.
    """
    
    site_name = "Generic IIIF"
    site_id = "generic_iiif"
    site_domains = []  # Will be matched via can_handle
    
    _manifest_url: str = ""
    
    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Check if URL is a IIIF manifest."""
        return "manifest" in url.lower() and url.endswith(".json")
    
    def extract_book_id(self, url: str) -> str:
        """For generic IIIF, the URL itself is the identifier."""
        self._manifest_url = url
        # Extract a reasonable ID from URL path
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        # Find part that looks like an ID (before 'manifest')
        for i, part in enumerate(path_parts):
            if "manifest" in part.lower() and i > 0:
                return path_parts[i - 1]
        return path_parts[-2] if len(path_parts) > 1 else "unknown"
    
    def get_manifest_url(self, book_id: str) -> str:
        """Return the stored manifest URL."""
        return self._manifest_url
