# Base Site Adapter - Abstract base class for all site adapters

from abc import ABC, abstractmethod
from typing import List, Optional, Type, Dict, Any, Callable
from urllib.parse import urlparse
import re

from ..models.book import BookMetadata, Resource
from ..models.manifest import (
    DownloadManifest, ManifestNode, NodeStatus, NodeType, ResourceKind,
)
from ..models.search import SearchResponse
from ..text_parsers.base import StructuredText


class BaseSiteAdapter(ABC):
    """
    Abstract base class for site adapters.
    
    Each site adapter handles a specific digital library website,
    implementing metadata extraction and resource listing.
    """
    
    # Class attributes for adapter registration
    site_name: str = ""                 # Human-readable name
    site_id: str = ""                   # Internal identifier
    site_domains: List[str] = []        # Domains this adapter handles
    
    # Capability flags
    supports_iiif: bool = False
    supports_text: bool = False
    supports_images: bool = True
    supports_pdf: bool = False
    supports_search: bool = False
    
    # HTTP configuration
    default_headers: Dict[str, str] = {}
    requires_auth: bool = False
    
    def __init__(self, config: Any = None):
        """Initialize the adapter with optional configuration."""
        self.config = config
        self._session = None
    
    @classmethod
    def can_handle(cls, url: str) -> bool:
        """
        Check if this adapter can handle the given URL.
        
        Default implementation checks if URL domain matches site_domains.
        Override for more complex URL matching.
        """
        if not cls.site_domains:
            return False
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            for site_domain in cls.site_domains:
                if site_domain.lower() in domain:
                    return True
        except Exception:
            pass
        
        return False
    
    @abstractmethod
    def extract_book_id(self, url: str) -> str:
        """
        Extract the book ID from a URL.
        
        Args:
            url: The URL to extract ID from
            
        Returns:
            The extracted book ID string
        """
        pass
    
    @abstractmethod
    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """
        Fetch complete metadata for a book.
        
        Args:
            book_id: The book identifier
            
        Returns:
            BookMetadata object with all available information
        """
        pass
    
    @abstractmethod
    async def get_image_list(self, book_id: str) -> List[Resource]:
        """
        Get list of image resources for the book.
        
        Args:
            book_id: The book identifier
            
        Returns:
            List of Resource objects for images
        """
        pass
    
    async def get_structured_text(
        self, book_id: str, index_id: str = "",
        progress_callback: Callable[[int, int], None] = None,
    ) -> Optional[StructuredText]:
        """
        Get structured text content if available.

        Returns a StructuredText object preserving chapter/paragraph hierarchy.
        Override in subclasses that support text resources.

        Args:
            book_id: The book identifier
            progress_callback: Optional callback (downloaded, total)

        Returns:
            StructuredText object or None if not available
        """
        return None

    async def get_text_content(self, book_id: str, index_id: str = "") -> Optional[str]:
        """
        Get text content as plain string.

        Default implementation converts from structured text if available.
        Override in subclasses for custom behavior.

        Args:
            book_id: The book identifier

        Returns:
            Text content string or None if not available
        """
        structured = await self.get_structured_text(book_id, index_id=index_id)
        if structured:
            from ..text_converters import PlainTextConverter
            return PlainTextConverter().convert(structured.to_dict())
        return None
    
    async def get_iiif_manifest(self, book_id: str) -> Optional[dict]:
        """
        Get IIIF manifest if available.
        
        Override in subclasses that support IIIF.
        
        Args:
            book_id: The book identifier
            
        Returns:
            IIIF manifest as dict or None if not available
        """
        return None
    
    async def get_pdf_url(self, book_id: str) -> Optional[str]:
        """
        Get PDF download URL if available.
        
        Override in subclasses that support PDF downloads.
        
        Args:
            book_id: The book identifier
            
        Returns:
            PDF URL string or None if not available
        """
        return None
    
    # ------------------------------------------------------------------
    # Search (optional capability)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search for books on this site.

        Override in adapters that support search (set supports_search = True).

        Args:
            query: Search keywords
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            SearchResponse with results
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support search"
        )

    # ------------------------------------------------------------------
    # Incremental discovery & download (new API)
    # ------------------------------------------------------------------

    async def discover_structure(
        self,
        book_id: str,
        index_id: str = "",
        depth: int = 1,
        progress_callback: Callable[[str, str], None] = None,
    ) -> DownloadManifest:
        """Discover the book's structure as a manifest tree.

        Override in adapters that support progressive/lazy discovery.
        Default implementation builds a flat manifest from the existing
        get_image_list() / get_metadata() methods.

        Args:
            book_id: The book identifier
            index_id: Optional global index ID
            depth: How deep to expand (-1 = full, 1 = top level only)
            progress_callback: callback(event_type, message)
        """
        return await self._discover_from_legacy(book_id, index_id)

    async def expand_node(
        self,
        book_id: str,
        manifest: DownloadManifest,
        node_id: str,
        depth: int = 1,
        progress_callback: Callable[[str, str], None] = None,
    ) -> Optional[ManifestNode]:
        """Expand a specific node in an existing manifest.

        Override for adapters with lazy tree expansion (e.g. Hanchi).
        Default: no-op, returns the node unchanged.
        """
        node = manifest.find_node(node_id)
        if node:
            node.expandable = False
        return node

    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: "Path",
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """Download content for a single manifest node.

        Override in adapters that need custom per-node download logic.
        Default raises NotImplementedError — adapters using the new API
        must implement this.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement download_node")

    async def _discover_from_legacy(
        self, book_id: str, index_id: str = "",
    ) -> DownloadManifest:
        """Build a flat manifest from legacy get_image_list() + get_metadata().

        Used as fallback for adapters that haven't overridden
        discover_structure().
        """
        from pathlib import Path

        metadata = await self.get_metadata(book_id, index_id=index_id)
        manifest = DownloadManifest(
            book_id=book_id,
            source_url=metadata.source_url or "",
            source_site=self.site_id,
            title=metadata.title,
            metadata={
                k: v for k, v in metadata.to_dict().items()
                if k in ("title", "creators", "dynasty", "category",
                         "volumes", "pages", "collection_unit")
                and v
            },
        )

        root = ManifestNode(
            id=book_id,
            title=metadata.title,
            node_type=NodeType.ROOT,
            status=NodeStatus.DISCOVERED,
        )

        # Group images by volume
        if self.supports_images:
            images = await self.get_image_list(book_id)
            if images:
                volumes: dict[str, list] = {}
                for img in images:
                    vol = img.volume or "default"
                    volumes.setdefault(vol, []).append(img)

                for vol_id, vol_images in sorted(volumes.items()):
                    vol_node = ManifestNode(
                        id=f"vol_{vol_id}",
                        title=f"Volume {vol_id}" if vol_id != "default" else "Images",
                        node_type=NodeType.VOLUME,
                        status=NodeStatus.DISCOVERED,
                        resource_kind=ResourceKind.IMAGE,
                        image_count=len(vol_images),
                        total_items=len(vol_images),
                        source_data={
                            "image_urls": [img.url for img in vol_images],
                            "images": [
                                {
                                    "url": img.url,
                                    "filename": img.get_filename(),
                                    "page": img.page,
                                    "volume": img.volume,
                                }
                                for img in vol_images
                            ],
                        },
                    )
                    root.children.append(vol_node)
                root.image_count = len(images)

        # Text as a single node
        if self.supports_text:
            text_node = ManifestNode(
                id=f"{book_id}_text",
                title="Full Text",
                node_type=NodeType.CHAPTER,
                status=NodeStatus.DISCOVERED,
                resource_kind=ResourceKind.TEXT,
                text_count=1,
                total_items=1,
            )
            root.children.append(text_node)
            root.text_count = 1

        root.children_count = len(root.children)
        manifest.root = root
        manifest.discovery_complete = True
        return manifest

    def get_headers(self, url: str = None) -> Dict[str, str]:
        """
        Get HTTP headers for requests to this site.
        
        Override to customize headers per-request.
        """
        headers = dict(self.default_headers)
        
        # Add default User-Agent if not already set
        if "User-Agent" not in headers:
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        if self.config and hasattr(self.config, 'download'):
            headers["User-Agent"] = self.config.download.user_agent
        return headers
    
    async def close(self):
        """Clean up resources (e.g., close HTTP session)."""
        if self._session:
            await self._session.close()
            self._session = None
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} site='{self.site_name}'>"
