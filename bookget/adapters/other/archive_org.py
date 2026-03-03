# Internet Archive (archive.org) Adapter

import re
from typing import List, Optional
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...logger import logger
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class ArchiveOrgAdapter(BaseSiteAdapter):
    """
    Adapter for Internet Archive (archive.org).

    Supports downloading page images from digitized books via the
    BookReader API or direct TIFF ZIP downloads.

    URL patterns:
    - Detail: https://archive.org/details/{identifier}
    - Page:   https://archive.org/details/{identifier}/page/n{N}/mode/2up

    Image download via BookReader API:
    - https://{server}/BookReader/BookReaderImages.php?
        zip={dir}/{id}_tif.zip&
        file={id}_tif/{id}_{page:04d}.tif&
        id={id}&scale=1&rotate=0
    """

    site_name = "Internet Archive"
    site_id = "archive_org"
    site_domains = ["archive.org", "www.archive.org"]

    supports_iiif = False
    supports_text = False
    supports_images = True
    supports_pdf = True

    def __init__(self, config=None):
        super().__init__(config)
        self._session = None
        self._metadata_cache = {}

    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def extract_book_id(self, url: str) -> str:
        """Extract identifier from archive.org URL.

        Examples:
        - https://archive.org/details/06064237.cn → 06064237.cn
        - https://archive.org/details/06064237.cn/page/n23/mode/2up → 06064237.cn
        """
        match = re.search(r'archive\.org/details/([^/?#]+)', url)
        if match:
            return match.group(1)

        match = re.search(r'archive\.org/download/([^/?#]+)', url)
        if match:
            return match.group(1)

        raise MetadataExtractionError(f"Could not extract identifier from URL: {url}")

    async def _fetch_ia_metadata(self, identifier: str) -> dict:
        """Fetch and cache metadata from archive.org API."""
        if identifier in self._metadata_cache:
            return self._metadata_cache[identifier]

        session = await self.get_session()
        url = f"https://archive.org/metadata/{identifier}"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"Archive.org metadata API returned {response.status} for {identifier}")
                    return {}
                data = await response.json()
                self._metadata_cache[identifier] = data
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch archive.org metadata for {identifier}: {e}")
            return {}

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Fetch metadata from archive.org metadata API."""
        data = await self._fetch_ia_metadata(book_id)
        if not data:
            return BookMetadata(source_id=book_id, source_site="archive_org")

        ia_meta = data.get("metadata", {})

        metadata = BookMetadata(
            source_id=book_id,
            source_url=f"https://archive.org/details/{book_id}",
            source_site="archive_org",
            index_id=index_id,
        )

        metadata.title = ia_meta.get("title", "")
        metadata.language = ia_meta.get("language", "")
        metadata.rights = ia_meta.get("licenseurl", "")
        metadata.collection_unit = ia_meta.get("contributor", "")

        # Parse creators
        creator = ia_meta.get("creator", "")
        if isinstance(creator, list):
            for c in creator:
                metadata.creators.append(Creator(name=c))
        elif creator:
            metadata.creators.append(Creator(name=creator))

        # Parse page count from files list
        files = data.get("files", [])
        tif_count = sum(1 for f in files
                        if f.get("source") == "derivative"
                        and f.get("name", "").endswith("_tif.zip"))

        # Count actual TIF pages from scandata or file listing
        for f in files:
            name = f.get("name", "")
            if name.endswith("_tif.zip"):
                # Try to get file count from the TIF zip
                pass

        # Get imagecount from metadata if available
        imagecount = ia_meta.get("imagecount", "0")
        try:
            metadata.pages = int(imagecount)
        except (ValueError, TypeError):
            metadata.pages = 0

        metadata.raw_metadata = ia_meta
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Get list of page images using BookReader API.

        Strategy:
        1. Fetch metadata to get server, dir, and page count
        2. Construct BookReader image URLs for each page
        """
        data = await self._fetch_ia_metadata(book_id)
        if not data:
            return []

        server = data.get("d1", "") or data.get("server", "")
        d = data.get("dir", "")
        ia_meta = data.get("metadata", {})

        if not server or not d:
            logger.warning(f"Missing server/dir info for {book_id}")
            return []

        # Get total page count
        imagecount = 0
        try:
            imagecount = int(ia_meta.get("imagecount", "0"))
        except (ValueError, TypeError):
            pass

        if imagecount == 0:
            # Try to count TIF files in the file list
            files = data.get("files", [])
            tif_files = [f for f in files if f.get("name", "").endswith(".tif")
                         and "/" in f.get("name", "")]
            imagecount = len(tif_files)

        if imagecount == 0:
            logger.warning(f"Could not determine page count for {book_id}")
            return []

        logger.info(f"Archive.org {book_id}: {imagecount} pages on {server}")

        resources = []
        for page_num in range(1, imagecount + 1):
            page_str = f"{page_num:04d}"

            # BookReader API URL for individual page as JPEG
            img_url = (
                f"https://{server}/BookReader/BookReaderImages.php?"
                f"zip={d}/{book_id}_tif.zip&"
                f"file={book_id}_tif/{book_id}_{page_str}.tif&"
                f"id={book_id}&scale=1&rotate=0"
            )

            resource = Resource(
                url=img_url,
                resource_type=ResourceType.IMAGE,
                order=page_num,
                page=str(page_num),
                filename=f"{book_id}_{page_str}.jpg",
            )
            resources.append(resource)

        return resources

    async def get_pdf_url(self, book_id: str) -> Optional[str]:
        """Get PDF download URL."""
        return f"https://archive.org/download/{book_id}/{book_id}.pdf"

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
