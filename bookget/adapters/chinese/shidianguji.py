# 识典古籍 (Shidianguji) Adapter
# https://www.shidianguji.com/

import re
from typing import List, Optional
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...text_parsers.base import StructuredText
from ...text_parsers.shidianguji_parser import ShidianGujiParser
from ...logger import logger
from ...exceptions import MetadataExtractionError, DownloadError


@AdapterRegistry.register
class ShidianGujiAdapter(BaseSiteAdapter):
    """
    Adapter for 识典古籍 (shidianguji.com).
    
    This platform is operated by Beijing University and provides 
    both images and transcribed text. Uses custom API.
    
    URL patterns:
    - Book detail: https://www.shidianguji.com/book/{book_id}
    - Book list: https://www.shidianguji.com/bookList
    """
    
    site_name = "识典古籍"
    site_id = "shidianguji"
    site_domains = ["shidianguji.com", "www.shidianguji.com"]
    
    supports_iiif = False
    supports_images = True
    supports_text = True  # Has transcribed text
    
    BASE_URL = "https://www.shidianguji.com"
    API_URL = "https://dushu.qq.com/cgi-bin/app_portal"
    
    default_headers = {
        "Accept": "application/json",
        "Referer": "https://www.shidianguji.com/",
    }
    
    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session
    
    def extract_book_id(self, url: str) -> str:
        """Extract book ID from URL."""
        match = re.search(r'/book/([a-zA-Z0-9_]+)', url)
        if match:
            return match.group(1)
        
        raise MetadataExtractionError(f"Could not extract book ID from URL: {url}")
    
    async def get_metadata(self, book_id: str) -> BookMetadata:
        """Fetch book metadata."""
        session = await self.get_session()
        
        # Shidianguji uses a GraphQL-style API
        params = {
            "cmd": "book_info",
            "book_id": book_id,
        }
        
        try:
            async with session.get(self.API_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                
                if data.get("ret") != 0:
                    raise MetadataExtractionError(f"API error: {data.get('msg', 'Unknown')}")
                
                return self._parse_metadata(data.get("book_info", {}), book_id)
                
        except aiohttp.ClientError as e:
            raise MetadataExtractionError(f"Failed to fetch metadata: {e}")
    
    def _parse_metadata(self, data: dict, book_id: str) -> BookMetadata:
        """Parse API response into BookMetadata."""
        metadata = BookMetadata(source_id=book_id)
        
        metadata.title = data.get("name", "")
        metadata.dynasty = data.get("dynasty", "")
        
        # Parse author
        author = data.get("author", "")
        if author:
            metadata.creators.append(Creator(name=author))
        
        # Category
        metadata.category = data.get("category", "")
        
        # Volume info
        metadata.volume_info = data.get("volumes_count", "")
        
        # Description
        desc = data.get("intro", "")
        if desc:
            metadata.notes.append(desc)
        
        metadata.raw_metadata = data
        return metadata
    
    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Get list of images for the book."""
        session = await self.get_session()
        
        params = {
            "cmd": "book_chapter_list",
            "book_id": book_id,
        }
        
        try:
            async with session.get(self.API_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                
                resources = []
                chapters = data.get("chapter_list", [])
                
                for idx, chapter in enumerate(chapters):
                    # Get image URL for each chapter/page
                    img_url = chapter.get("img_url", "")
                    if img_url:
                        resource = Resource(
                            url=img_url,
                            resource_type=ResourceType.IMAGE,
                            order=idx + 1,
                            page=chapter.get("title", str(idx + 1)),
                        )
                        resources.append(resource)
                
                return resources
                
        except aiohttp.ClientError as e:
            raise DownloadError(f"Failed to get image list: {e}")
    
    async def get_structured_text(self, book_id: str) -> Optional[StructuredText]:
        """Get transcribed text as structured data."""
        session = await self.get_session()

        params = {
            "cmd": "book_chapter_list",
            "book_id": book_id,
        }

        try:
            async with session.get(self.API_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                chapter_list = data.get("chapter_list", [])
                if not chapter_list:
                    return None

                # Get metadata for title/author info
                try:
                    metadata = await self.get_metadata(book_id)
                    meta = {
                        "title": metadata.title,
                        "author": metadata.creators[0].name if metadata.creators else "",
                        "dynasty": metadata.dynasty,
                        "category": metadata.category,
                    }
                except Exception:
                    meta = {}

                parser = ShidianGujiParser()
                url = f"{self.BASE_URL}/book/{book_id}"
                return parser.parse(chapter_list, book_id, url, meta)

        except Exception as e:
            logger.warning(f"Failed to get structured text: {e}")
            return None
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
