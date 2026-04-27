# Kyoto University Rare Materials Digital Archive Adapter
# https://rmda.kulib.kyoto-u.ac.jp/

import os
import re
from typing import List, Any
from urllib.parse import urlparse

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...logger import logger


@AdapterRegistry.register
class KyotoRMDAAdapter(BaseIIIFAdapter):
    """
    Adapter for Kyoto University Rare Materials Digital Archive (RMDA).

    The site exposes IIIF Presentation API 3.0 manifests at:
        https://rmda.kulib.kyoto-u.ac.jp/iiif/metadata_manifest/{ID}/manifest.json

    Item pages look like:
        https://rmda.kulib.kyoto-u.ac.jp/en/item/RB00012961
        https://rmda.kulib.kyoto-u.ac.jp/item/RB00012961
    """

    site_name = "京都大学贵重资料数字档案馆 (Kyoto RMDA)"
    site_id = "kyoto_rmda"
    site_domains = ["rmda.kulib.kyoto-u.ac.jp"]

    supports_iiif = True
    supports_text = False

    # RMDA serves IIIF Presentation 3.0; "max" is the canonical "original size"
    # parameter (≈4 MB JPEG for typical pages). Use BOOKGET_KYOTO_IIIF_SIZE
    # or BOOKGET_IIIF_SIZE env var to override (e.g. "2400," / "1600,").
    DEFAULT_IIIF_SIZE = "max"

    def extract_book_id(self, url: str) -> str:
        """
        Extract the RMDA record ID (e.g. RB00012961) from a URL.

        Accepts:
        - /item/RB00012961, /en/item/RB00012961
        - /iiif/metadata_manifest/RB00012961/manifest.json
        - /iiif/RB00012961/canvas/p1
        """
        for pattern in (
            r"/item/([A-Za-z0-9_-]+)",
            r"/iiif/metadata_manifest/([A-Za-z0-9_-]+)",
            r"/iiif/([A-Za-z]{1,3}\d{6,})",
        ):
            m = re.search(pattern, url)
            if m:
                # Canonicalize to uppercase (matches RMDA's record IDs).
                return m.group(1).upper()
        raise ValueError(f"Could not extract RMDA book ID from URL: {url}")

    def get_manifest_url(self, book_id: str) -> str:
        return f"https://rmda.kulib.kyoto-u.ac.jp/iiif/metadata_manifest/{book_id}/manifest.json"

    # ------------------------------------------------------------------
    # IIIF Presentation API 3.0 parsing
    # ------------------------------------------------------------------

    def _extract_label(self, value: Any) -> str:
        """
        Extract a label string from IIIF 3 value object.

        IIIF 3 uses {"<lang>": ["text", ...]} maps. Prefer ja, then en, zh, none.
        Falls back to base class behavior for IIIF 2 / mixed forms.
        """
        if isinstance(value, dict):
            # IIIF 3 language map: {"ja": ["..."], "en": ["..."]}
            for lang in ("ja", "zh", "en", "und", "none"):
                if lang in value:
                    v = value[lang]
                    if isinstance(v, list) and v:
                        return str(v[0])
                    if isinstance(v, str):
                        return v
        return super()._extract_label(value)

    @staticmethod
    def _strip_html(s: str) -> str:
        """Strip HTML tags from a string (RMDA puts <a><strong>... in some labels)."""
        return re.sub(r"<[^>]+>", "", s).strip()

    def _parse_manifest_metadata(self, manifest: dict, book_id: str) -> BookMetadata:
        """Parse Kyoto RMDA IIIF 3 manifest into BookMetadata."""
        metadata = BookMetadata(
            source_id=book_id,
            iiif_manifest_url=self.get_manifest_url(book_id),
        )

        title_raw = self._extract_label(manifest.get("label", ""))
        metadata.title = self._strip_html(title_raw)

        for item in manifest.get("metadata", []) or []:
            label = self._strip_html(self._extract_label(item.get("label", "")))
            value = self._strip_html(self._extract_label(item.get("value", "")))
            if not value:
                continue

            # RMDA labels are mostly Japanese: タイトル / 著者, レコードID, コレクション
            if "タイトル" in label or "著者" in label or "title" in label.lower():
                # Format: "<title> / <author>(role)著"
                if " / " in value:
                    t_part, a_part = value.split(" / ", 1)
                    if not metadata.title:
                        metadata.title = t_part.strip()
                    creator_name = a_part.strip()
                    if creator_name:
                        metadata.creators.append(Creator(name=creator_name))
                else:
                    if not metadata.title:
                        metadata.title = value
            elif "レコード" in label or "record" in label.lower():
                # Already have source_id; preserve as note for traceability
                pass
            elif "コレクション" in label or "collection" in label.lower():
                metadata.collection_unit = value
            elif "言語" in label or "language" in label.lower():
                metadata.language = value
            elif "出版" in label or "date" in label.lower() or "年" in label:
                metadata.date = value

        # Required statement (holding institution)
        req = manifest.get("requiredStatement", {})
        if req:
            req_value = self._strip_html(self._extract_label(req.get("value", "")))
            if req_value and not metadata.collection_unit:
                metadata.collection_unit = req_value

        rights = manifest.get("rights")
        if isinstance(rights, str):
            metadata.rights = rights

        metadata.pages = len(manifest.get("items", []) or [])
        metadata.raw_metadata = manifest
        return metadata

    def _parse_manifest_images(self, manifest: dict) -> List[Resource]:
        """
        Parse images from a IIIF Presentation API 3.0 manifest.

        Structure:
            manifest.items[]            -> Canvas
                .items[]                -> AnnotationPage
                    .items[]            -> Annotation (motivation=painting)
                        .body           -> Image resource (id, service[].id)
                .annotations[]          -> AnnotationPage (volume label etc.)
        """
        resources: List[Resource] = []
        canvases = manifest.get("items", []) or []
        size = self.iiif_size

        for idx, canvas in enumerate(canvases):
            page_label = self._extract_label(canvas.get("label", "")) or str(idx + 1)

            # Volume info from canvas annotations (RMDA puts 巻号 here).
            volume = self._extract_volume_from_annotations(canvas)

            # Walk to the painting annotation body.
            body = None
            for ann_page in canvas.get("items", []) or []:
                for ann in ann_page.get("items", []) or []:
                    if ann.get("motivation") == "painting":
                        body = ann.get("body")
                        break
                if body:
                    break
            if not body:
                logger.warning(f"No painting annotation on canvas {idx + 1}")
                continue

            # body may be a dict (single image) or list (choice).
            if isinstance(body, list):
                body = body[0] if body else {}

            image_url = body.get("id", "")

            service = body.get("service") or []
            if isinstance(service, dict):
                service = [service]
            service_id = service[0].get("id", "") if service else ""

            # Build a sized image URL from the service base when available.
            if service_id:
                image_url = f"{service_id}/full/{size}/0/default.jpg"

            width = body.get("width") or canvas.get("width", 0)
            height = body.get("height") or canvas.get("height", 0)

            # Filename: v{vol}_{order:04d}.jpg, e.g. v01_0001.jpg
            order = idx + 1
            if volume:
                filename = f"v{volume}_{order:04d}.jpg"
            else:
                filename = f"{order:04d}.jpg"

            resources.append(Resource(
                url=image_url,
                resource_type=ResourceType.IMAGE,
                order=order,
                volume=volume,
                page=str(page_label),
                filename=filename,
                iiif_service_id=service_id,
                width=width,
                height=height,
            ))

        return resources

    def _extract_volume_from_annotations(self, canvas: dict) -> str:
        """RMDA stores 巻号 (volume number) in commenting annotations on each canvas."""
        for ann_page in canvas.get("annotations", []) or []:
            for ann in ann_page.get("items", []) or []:
                body = ann.get("body", {})
                value = body.get("value", "") if isinstance(body, dict) else ""
                if "巻号" in value:
                    m = re.search(
                        r'annotation-value[^>]*>([^<]+)<', value)
                    if m:
                        return m.group(1).strip()
        return ""

    def get_headers(self, url: str = "") -> dict:
        h = dict(self.default_headers or {})
        h.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) bookget/0.2",
        )
        h.setdefault("Accept", "application/json, image/jpeg, */*")
        return h
