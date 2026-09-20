# Internet Archive (archive.org) Adapter

import re
from typing import List, Optional, Tuple
from urllib.parse import urlencode
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

        # Get imagecount from metadata if available
        imagecount = ia_meta.get("imagecount", "0")
        try:
            metadata.pages = int(imagecount)
        except (ValueError, TypeError):
            metadata.pages = 0

        metadata.raw_metadata = ia_meta
        return metadata

    # Image derivatives, best first. Modern IA scans ship JP2; only older
    # items still carry a TIF stack, and a handful carry plain JPEGs.
    _IMAGE_ZIP_SUFFIXES = ("_jp2.zip", "_tif.zip", "_jpg.zip")

    @classmethod
    def _find_image_derivative(
        cls, files: List[dict], identifier: str
    ) -> Optional[Tuple[str, str]]:
        """Locate the item's image stack, as ``(sub_prefix, kind)``.

        The derivative is NOT always named after the identifier: item
        ``in.ernet.dli.2015.282`` ships
        ``2015.282.Tory-Lives-From-Falkland-To-Disraeli_jp2.zip``. Assuming
        ``{identifier}_tif.zip`` (what this adapter used to do) misses every
        such item, and every JP2-only item besides. Prefer the derivative
        actually named after the identifier, since items can carry several
        stacks (``_orig_tif.zip`` next to ``_tif.zip``).
        """
        names = [f.get("name", "") for f in files if isinstance(f, dict)]
        for suffix in cls._IMAGE_ZIP_SUFFIXES:
            kind = suffix[1:-4]  # "_jp2.zip" -> "jp2"
            if f"{identifier}{suffix}" in names:
                return identifier, kind
            for name in names:
                if name.endswith(suffix) and "/" not in name:
                    return name[: -len(suffix)], kind
        return None

    @staticmethod
    def _resources_from_jsia(book_id: str, payload: dict) -> List[Resource]:
        """Turn a BookReaderJSIA payload into page resources.

        ``brOptions.data`` is a list of *spreads*, each a list of page dicts,
        so it has to be flattened rather than counted.
        """
        br = ((payload or {}).get("data") or {}).get("brOptions") or {}
        resources: List[Resource] = []
        for spread in br.get("data") or []:
            pages = spread if isinstance(spread, list) else [spread]
            for page in pages:
                uri = (page or {}).get("uri")
                if not uri:
                    continue
                try:
                    leaf = int(page.get("leafNum", len(resources) + 1))
                except (TypeError, ValueError):
                    leaf = len(resources) + 1
                resources.append(Resource(
                    url=uri,
                    resource_type=ResourceType.IMAGE,
                    order=leaf,
                    page=str(leaf),
                    # BookReaderImages.php always answers JPEG, whatever the
                    # stack it reads from.
                    filename=f"{book_id}_{leaf:04d}.jpg",
                ))
        return resources

    @staticmethod
    def _resources_from_template(
        book_id: str, server: str, item_path: str,
        sub_prefix: str, kind: str, count: int,
    ) -> List[Resource]:
        """Build page URLs by hand, for items BookReader refuses to serve."""
        resources = []
        for page_num in range(1, count + 1):
            page_str = f"{page_num:04d}"
            img_url = (
                f"https://{server}/BookReader/BookReaderImages.php?"
                f"zip={item_path}/{sub_prefix}_{kind}.zip&"
                f"file={sub_prefix}_{kind}/{sub_prefix}_{page_str}.{kind}&"
                f"id={book_id}&scale=1&rotate=0"
            )
            resources.append(Resource(
                url=img_url,
                resource_type=ResourceType.IMAGE,
                order=page_num,
                page=str(page_num),
                filename=f"{book_id}_{page_str}.jpg",
            ))
        return resources

    async def _pages_from_bookreader(
        self, book_id: str, server: str, item_path: str, sub_prefix: str,
    ) -> List[Resource]:
        """Ask BookReader itself for the page list."""
        params = {
            "id": book_id,
            "itemPath": item_path,
            "server": server,
            "format": "json",
        }
        if sub_prefix:
            params["subPrefix"] = sub_prefix
        url = f"https://{server}/BookReader/BookReaderJSIA.php?{urlencode(params)}"

        session = await self.get_session()
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(
                        f"BookReader API returned {response.status} for {book_id}")
                    return []
                # content_type=None: the endpoint has been seen answering
                # with a non-JSON content type, which strict .json() rejects.
                payload = await response.json(content_type=None)
        except Exception as e:
            logger.warning(f"BookReader API failed for {book_id}: {e}")
            return []

        error = (payload or {}).get("error")
        if error:
            logger.warning(f"BookReader API error for {book_id}: {error}")
            return []
        return self._resources_from_jsia(book_id, payload)

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Get the item's page images.

        BookReader's own JSIA endpoint is the source of truth: it knows the
        derivative prefix, the page count and the per-page URLs, so it covers
        JP2-only items and items whose derivative is not named after the
        identifier. The hand-built template stays as a fallback for items it
        refuses to serve.
        """
        data = await self._fetch_ia_metadata(book_id)
        if not data:
            raise MetadataExtractionError(
                f"archive.org metadata API returned nothing for {book_id}")

        server = data.get("d1", "") or data.get("server", "")
        item_path = data.get("dir", "")
        if not server or not item_path:
            raise MetadataExtractionError(
                f"archive.org metadata for {book_id} carries no server/dir; "
                f"the item may be dark or purely a collection")

        derivative = self._find_image_derivative(data.get("files", []), book_id)
        sub_prefix, kind = derivative if derivative else (book_id, "jp2")

        resources = await self._pages_from_bookreader(
            book_id, server, item_path, sub_prefix)
        if resources:
            logger.info(
                f"Archive.org {book_id}: {len(resources)} pages via BookReader "
                f"(stack: {sub_prefix}_{kind})")
            return resources

        imagecount = 0
        try:
            imagecount = int(data.get("metadata", {}).get("imagecount", 0))
        except (ValueError, TypeError):
            imagecount = 0

        if derivative and imagecount:
            logger.info(
                f"Archive.org {book_id}: BookReader gave nothing, falling back "
                f"to {imagecount} templated pages (stack: {sub_prefix}_{kind})")
            return self._resources_from_template(
                book_id, server, item_path, sub_prefix, kind, imagecount)

        # This used to `return []`, which made the adapter report a successful
        # download of zero images. An empty page list is a failure, not a result.
        stacks = sorted({
            f.get("name", "") for f in data.get("files", [])
            if f.get("name", "").endswith(".zip")
        })
        raise MetadataExtractionError(
            f"archive.org item {book_id}: BookReader returned no pages and the "
            f"item has no usable image derivative (zips present: {stacks or 'none'}). "
            f"Items that are audio/video, lending-restricted or text-only have no "
            f"page images to download.")

    async def get_pdf_url(self, book_id: str) -> Optional[str]:
        """Get PDF download URL."""
        return f"https://archive.org/download/{book_id}/{book_id}.pdf"

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
