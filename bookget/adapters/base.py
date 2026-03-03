# Base Site Adapter - Abstract base class for all site adapters

from abc import ABC, abstractmethod
from typing import List, Optional, Type, Dict, Any
from urllib.parse import urlparse
import re

from ..models.book import BookMetadata, Resource
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
    
    async def get_structured_text(self, book_id: str, index_id: str = "") -> Optional[StructuredText]:
        """
        Get structured text content if available.

        Returns a StructuredText object preserving chapter/paragraph hierarchy.
        Override in subclasses that support text resources.

        Args:
            book_id: The book identifier

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
