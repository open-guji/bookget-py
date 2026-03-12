# 中华古籍智慧化服务平台 (NLC Guji) Adapter
# https://guji.nlc.cn/

import asyncio
import re
from typing import List, Optional, Dict, Any
from urllib.parse import quote
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...text_parsers.base import StructuredText
from ...logger import logger
from ...exceptions import MetadataExtractionError, DownloadError


@AdapterRegistry.register
class NLCGujiAdapter(BaseSiteAdapter):
    """
    Adapter for 中华古籍智慧化服务平台 (NLC Guji).

    This is the National Library of China's ancient books platform.
    Uses custom REST API (not IIIF).

    Download flow (2-step image resolution):
    1. POST ancImageIdListWithPageNum → get image IDs
    2. POST ancImageAndContent per image → get filePath + OCR text
    3. GET jpgViewer?ftpId=1&filePathName={encoded_filePath} → download image
    """

    site_name = "中华古籍智慧化服务平台"
    site_id = "nlc_guji"
    site_domains = ["guji.nlc.cn"]

    supports_iiif = False
    supports_images = True
    supports_text = True  # Platform provides OCR text

    BASE_URL = "https://guji.nlc.cn"

    # Required headers for API access
    default_headers = {
        "Content-Type": "application/json",
        "Referer": "https://guji.nlc.cn/",
        "Origin": "https://guji.nlc.cn",
        "Accept": "application/json, text/plain, */*",
    }

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            headers = self.get_headers()
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Check if this adapter can handle the URL."""
        return "guji.nlc.cn" in url.lower()

    def extract_book_id(self, url: str) -> str:
        """
        Extract metadataId from URL.

        Patterns:
        - /guji/pjkf/detail?metadataId=0021001379780000
        - /resource/resourceDetail?id=1001254
        """
        # Try metadataId parameter first
        match = re.search(r'metadataId=([A-Za-z0-9_-]+)', url, re.IGNORECASE)
        if match:
            return match.group(1)

        # Try id parameter
        match = re.search(r'\?id=([A-Za-z0-9_-]+)', url, re.IGNORECASE)
        if match:
            return match.group(1)

        raise MetadataExtractionError(f"Could not extract book ID from URL: {url}")

    async def get_metadata(self, book_id: str) -> BookMetadata:
        """Fetch complete metadata from API."""
        session = await self.get_session()
        url = f"{self.BASE_URL}/api/anc/ancMetadataDetail/{book_id}"

        try:
            async with session.post(url) as response:
                response.raise_for_status()
                data = await response.json()

                if data.get("code") != 200:
                    raise MetadataExtractionError(f"API error: {data.get('msg', 'Unknown')}")

                return self._parse_metadata(data.get("data", {}), book_id)

        except aiohttp.ClientError as e:
            raise MetadataExtractionError(f"Failed to fetch metadata: {e}")

    def _parse_metadata(self, data: dict, book_id: str) -> BookMetadata:
        """Parse NLC API response into BookMetadata."""
        metadata = BookMetadata(source_id=book_id)

        # Parse title and creators from parallelTitle
        parallel_titles = data.get("parallelTitle", [])
        if parallel_titles:
            pt = parallel_titles[0]
            metadata.title = pt.get("title", "")

            # Parse creators
            for c in pt.get("creators", []):
                if c.get("creator"):
                    metadata.creators.append(Creator(
                        name=c.get("creator", ""),
                        role=c.get("role", ""),
                        dynasty=c.get("statementOfResponsiblePerson", "")
                    ))

        # Publication info
        publisher_data = data.get("publisher", {})
        publishing = publisher_data.get("publishing", [{}])[0] if publisher_data.get("publishing") else {}

        metadata.publisher = publishing.get("publisher", "")
        metadata.place = publishing.get("placeOfPublication", "")

        issued = publishing.get("issuedGregorian", {})
        metadata.dynasty = issued.get("issuedChineseCalendar", "")
        metadata.date = metadata.dynasty
        metadata.date_normalized = issued.get("issuedGregorianCalendar", "")

        # Physical description
        phys = data.get("physicalDescription", [{}])[0] if data.get("physicalDescription") else {}
        metadata.volume_info = phys.get("quantity", "")
        metadata.binding = phys.get("binding", "")
        dimensions = phys.get("dimension", [])
        metadata.dimensions = dimensions[0] if dimensions else ""

        # Description
        desc = data.get("description", [{}])[0] if data.get("description") else {}
        layout = desc.get("paragraphFormat", [])
        metadata.layout = layout[0] if layout else ""

        # Classification
        subject = data.get("subject", [{}])[0] if data.get("subject") else {}
        fdc = subject.get("fdc", [])
        metadata.category = fdc[0] if fdc else ""

        # Location
        location = data.get("location", [{}])[0] if data.get("location") else {}
        metadata.collection_unit = location.get("collectionUnit", "")
        call_numbers = location.get("callNumber", [])
        metadata.call_number = call_numbers[0] if call_numbers else ""

        # Other fields
        metadata.doc_type = data.get("type", "")
        metadata.language = data.get("language", "")

        # Provenance
        provenance = data.get("provenance", [{}])[0] if data.get("provenance") else {}
        for writer in provenance.get("inscriptionWriter", []):
            if writer.get("inscriptionWriter"):
                info = f"{writer.get('inscriptionWriter')} ({writer.get('inscriptionRole', '')})"
                metadata.provenance.append(info)

        # Store raw metadata
        metadata.raw_metadata = data

        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """
        Get list of all images with resolved download URLs.

        NLC requires a 2-step process:
        1. Get image ID list
        2. For each image, call ancImageAndContent to get filePath
        3. Build jpgViewer download URL from filePath
        """
        session = await self.get_session()

        # Step 1: Get image ID list
        url = f"{self.BASE_URL}/api/anc/ancImageIdListWithPageNum?metadataId={book_id}"
        try:
            async with session.post(url) as response:
                response.raise_for_status()
                data = await response.json()

                if data.get("code") != 200:
                    raise DownloadError(f"API error: {data.get('msg', 'Unknown')}")

                image_items = data.get("data", {}).get("imageIdList", [])

        except aiohttp.ClientError as e:
            raise DownloadError(f"Failed to get image list: {e}")

        if not image_items:
            logger.warning(f"No images found for {book_id}")
            return []

        logger.info(f"Found {len(image_items)} images, resolving download paths...")

        # Step 2: Get volume structure for organizing by volume
        structure = await self._get_structure(book_id)
        volume_titles = {}
        if structure:
            for vol in structure:
                sid = str(vol.get("structureId", ""))
                volume_titles[sid] = vol.get("volumeTitle", "")

        # Step 3: Resolve actual download URLs concurrently
        delay = self.config.download.request_delay if self.config else 0.3
        semaphore = asyncio.Semaphore(4)
        resources = []
        resolved_count = 0

        async def resolve_one(item):
            nonlocal resolved_count
            async with semaphore:
                image_id = str(item.get("imageId", ""))
                structure_id = str(item.get("structureId", ""))
                page_num = item.get("pageNum", 0)
                order = int(item.get("orderSeq", 0))

                download_url = await self._resolve_image_url(
                    book_id, structure_id, image_id
                )

                if download_url:
                    vol_title = volume_titles.get(structure_id, "")
                    resource = Resource(
                        url=download_url,
                        resource_type=ResourceType.IMAGE,
                        order=order,
                        volume=structure_id,
                        page=str(page_num),
                        filename=f"{order:04d}.jpg"
                    )
                    resource.iiif_service_id = f"{structure_id}|{image_id}"
                    resources.append(resource)
                    resolved_count += 1
                else:
                    logger.warning(f"Failed to resolve image {order} (id={image_id})")

                await asyncio.sleep(delay)

        await asyncio.gather(*[resolve_one(item) for item in image_items])

        # Sort by order
        resources.sort(key=lambda r: r.order)
        logger.info(f"Resolved {resolved_count}/{len(image_items)} image URLs")

        return resources

    async def _resolve_image_url(
        self, book_id: str, structure_id: str, image_id: str
    ) -> Optional[str]:
        """
        Resolve actual download URL for a single image.

        Calls ancImageAndContent to get filePath, then builds jpgViewer URL.
        """
        session = await self.get_session()
        url = (
            f"{self.BASE_URL}/api/anc/ancImageAndContent?"
            f"metadataId={book_id}&structureId={structure_id}&imageId={image_id}"
        )

        try:
            async with session.post(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if data.get("code") != 200:
                    return None

                file_path = data.get("data", {}).get("filePath", "")
                if not file_path:
                    return None

                # Build jpgViewer download URL
                encoded_path = quote(file_path, safe="")
                return (
                    f"{self.BASE_URL}/api/common/jpgViewer?"
                    f"ftpId=1&filePathName={encoded_path}"
                )
        except Exception as e:
            logger.debug(f"Failed to resolve image path (id={image_id}): {e}")
            return None

    async def _get_structure(self, book_id: str) -> Optional[List[dict]]:
        """
        Get volume/chapter structure for the book.

        Returns list of volume dicts with structureId, volumeTitle, fileNumber, etc.
        """
        session = await self.get_session()
        url = f"{self.BASE_URL}/api/anc/ancStructureAndCatalogList?metadataId={book_id}"

        try:
            async with session.post(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if data.get("code") != 200:
                    return None
                return data.get("data", [])
        except Exception as e:
            logger.debug(f"Failed to get structure for {book_id}: {e}")
            return None

    async def get_structured_text(self, book_id: str) -> Optional[StructuredText]:
        """
        Get OCR text content as structured data.

        NLC provides OCR text through the ancImageAndContent API.
        We fetch text for each page and organize by volume.
        """
        session = await self.get_session()

        # Get image list to know which pages to fetch
        url = f"{self.BASE_URL}/api/anc/ancImageIdListWithPageNum?metadataId={book_id}"
        try:
            async with session.post(url) as response:
                response.raise_for_status()
                data = await response.json()
                if data.get("code") != 200:
                    return None
                image_items = data.get("data", {}).get("imageIdList", [])
        except Exception as e:
            logger.warning(f"Failed to get image list for text: {e}")
            return None

        if not image_items:
            return None

        # Get volume structure
        structure = await self._get_structure(book_id)
        volume_titles = {}
        if structure:
            for vol in structure:
                sid = str(vol.get("structureId", ""))
                volume_titles[sid] = vol.get("volumeTitle", "")

        # Fetch OCR text for each page
        delay = self.config.download.request_delay if self.config else 0.3
        semaphore = asyncio.Semaphore(4)
        # {structure_id: [(order, text), ...]}
        volume_texts: Dict[str, List[tuple]] = {}

        async def fetch_text(item):
            async with semaphore:
                image_id = str(item.get("imageId", ""))
                structure_id = str(item.get("structureId", ""))
                order = int(item.get("orderSeq", 0))

                text = await self._fetch_page_text(
                    book_id, structure_id, image_id
                )
                if text:
                    if structure_id not in volume_texts:
                        volume_texts[structure_id] = []
                    volume_texts[structure_id].append((order, text))

                await asyncio.sleep(delay)

        logger.info(f"Fetching OCR text for {len(image_items)} pages...")
        await asyncio.gather(*[fetch_text(item) for item in image_items])

        # Check if we got any text
        total_texts = sum(len(v) for v in volume_texts.values())
        if total_texts == 0:
            logger.info("No OCR text available for this book")
            return None

        # Build structured text organized by volume
        chapters = []
        for i, (sid, texts) in enumerate(sorted(
            volume_texts.items(),
            key=lambda x: min(t[0] for t in x[1])
        )):
            texts.sort(key=lambda t: t[0])
            vol_title = volume_titles.get(sid, f"Volume {i+1}")
            chapters.append({
                "id": sid,
                "title": vol_title,
                "order": i + 1,
                "paragraphs": [t[1] for t in texts],
            })

        # Get metadata for title/authors
        try:
            metadata = await self.get_metadata(book_id)
            title = metadata.title
            authors = [
                {"name": c.name, "role": c.role, "dynasty": c.dynasty}
                for c in metadata.creators
            ]
            meta_dict = {
                "authors": authors,
                "dynasty": metadata.dynasty,
                "category": metadata.category,
                "collection_unit": metadata.collection_unit,
            }
        except Exception:
            title = ""
            meta_dict = {}

        content_type = "book_with_chapters" if len(chapters) > 1 else "single_chapter"

        structured = StructuredText(
            source=self._make_source(book_id),
            title=title,
            content_type=content_type,
            metadata=meta_dict,
            chapters=chapters,
        )

        logger.info(
            f"Extracted OCR text: {len(chapters)} volumes, "
            f"{total_texts} pages with text"
        )
        return structured

    def _make_source(self, book_id: str) -> dict:
        """Build source dict for StructuredText."""
        from datetime import datetime, timezone
        return {
            "site": self.site_id,
            "url": f"{self.BASE_URL}/guji/pjkf/detail?metadataId={book_id}",
            "book_id": book_id,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _fetch_page_text(
        self, book_id: str, structure_id: str, image_id: str
    ) -> Optional[str]:
        """
        Fetch OCR text for a single page via ancImageAndContent API.

        NLC stores OCR text in multiple fields:
        - trans.transResult[0].comma_result: punctuated plain text (best)
        - comma.commaResult: punctuated HTML (needs stripping)
        - recoJson.chars[].text: raw character recognition
        """
        session = await self.get_session()
        url = (
            f"{self.BASE_URL}/api/anc/ancImageAndContent?"
            f"metadataId={book_id}&structureId={structure_id}&imageId={image_id}"
        )

        try:
            async with session.post(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if data.get("code") != 200:
                    return None

                page_data = data.get("data", {})

                # Priority 1: trans.transResult[0].comma_result (punctuated plain text)
                trans = page_data.get("trans")
                if isinstance(trans, dict):
                    results = trans.get("transResult", [])
                    if results and isinstance(results, list):
                        comma_text = results[0].get("comma_result", "")
                        if comma_text and comma_text.strip():
                            return comma_text.strip()

                # Priority 2: comma.commaResult (HTML → strip tags)
                comma = page_data.get("comma")
                if isinstance(comma, dict):
                    html = comma.get("commaResult", "")
                    if html and html.strip():
                        text = self._strip_html_tags(html)
                        if text:
                            return text

                # Priority 3: recoJson chars (raw OCR)
                reco = page_data.get("recoJson")
                if isinstance(reco, dict):
                    chars = reco.get("chars", [])
                    if chars:
                        texts = []
                        for ch in chars:
                            t = ch.get("text", "")
                            if t and t != "[=此叶为空白叶页=]":
                                texts.append(t)
                        if texts:
                            return "".join(texts)

                return None
        except Exception:
            return None

    @staticmethod
    def _strip_html_tags(html: str) -> Optional[str]:
        """Strip HTML tags from commaResult, keeping text content."""
        import re as _re
        # Remove all HTML tags
        text = _re.sub(r'<[^>]+>', '', html)
        # Clean up whitespace
        text = text.strip()
        # Skip blank page markers
        if text == "[=此叶为空白叶页=]" or not text:
            return None
        return text

    async def get_text_content(self, book_id: str) -> Optional[str]:
        """
        Get OCR text content as plain text.
        Delegates to get_structured_text() and converts.
        """
        structured = await self.get_structured_text(book_id)
        if structured:
            from ...text_converters import PlainTextConverter
            return PlainTextConverter().convert(structured.to_dict())
        return None

    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
