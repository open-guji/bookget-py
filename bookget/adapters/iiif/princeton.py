# Princeton University Library Adapter
# https://dpul.princeton.edu/eastasian

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata
from ...logger import logger
from ...exceptions import MetadataExtractionError

# A figgy id is a dashed UUID; a DPUL (Spotlight) catalog id is 32 bare hex
# digits. They are different identifiers for the same object, so the catalog
# id cannot be dropped into the figgy manifest template.
_FIGGY_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                         r'[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


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

    NOTE: the catalog id is NOT the figgy id. dpul.princeton.edu runs
    Spotlight, whose ids are its own; the figgy manifest is named in the
    catalog record's `content_metadata_iiif_manifest_field_ssi` field and has
    to be looked up. Feeding the catalog id to the figgy template answers 404
    for every DPUL item.
    """

    site_name = "普林斯顿大学图书馆 (Princeton)"
    site_id = "princeton"
    site_domains = [
        "dpul.princeton.edu",
        "figgy.princeton.edu"
    ]

    supports_iiif = True
    supports_text = False

    def __init__(self, config=None):
        super().__init__(config)
        # catalog id -> resolved figgy manifest URL
        self._manifest_urls = {}

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
        """IIIF manifest URL: the resolved one when we have it."""
        resolved = self._manifest_urls.get(book_id)
        if resolved:
            return resolved
        return f"https://figgy.princeton.edu/concern/scanned_resources/{book_id}/manifest"

    async def _resolve_dpul_manifest(self, book_id: str) -> str:
        """Look up a DPUL catalog id's figgy manifest URL."""
        url = f"https://dpul.princeton.edu/catalog/{book_id}.json"
        session = await self.get_session()
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                record = await response.json(content_type=None)
        except Exception as e:
            raise MetadataExtractionError(
                f"[princeton] 取 DPUL 记录失败：{url}（{e}）") from e

        document = ((record or {}).get("response") or {}).get("document") or {}
        manifest_url = document.get("content_metadata_iiif_manifest_field_ssi")
        if not manifest_url:
            raise MetadataExtractionError(
                f"[princeton] DPUL 记录里没有 IIIF manifest 字段：{url}\n"
                f"（该条目可能没有数字化影像）")
        logger.info(f"Princeton {book_id} -> {manifest_url}")
        return manifest_url

    async def get_iiif_manifest(self, book_id: str):
        """Resolve the DPUL id to its figgy manifest before fetching."""
        if not _FIGGY_UUID.match(book_id) and book_id not in self._manifest_urls:
            self._manifest_urls[book_id] = await self._resolve_dpul_manifest(book_id)
        return await super().get_iiif_manifest(book_id)

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
