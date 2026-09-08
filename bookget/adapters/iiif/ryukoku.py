# 龍谷大學圖書館「龍谷蔵」(Ryukoku University Library) Adapter
# https://da.library.ryukoku.ac.jp/
#
# 佛教典籍、真宗文献等贵重资料。标准 IIIF Presentation 2.0，manifest 可推导：
#   item 页 /page/{id}  →  https://da.library.ryukoku.ac.jp/iiif/{id}/1/manifest.json
#
# URL patterns:
#   - Item page:     https://da.library.ryukoku.ac.jp/page/{id}
#   - IIIF manifest: https://da.library.ryukoku.ac.jp/iiif/{id}/1/manifest.json
#   ({id} 为数字，如 220901；末段 /1/ 为册序)

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class RyukokuAdapter(BaseIIIFAdapter):
    """Adapter for Ryukoku University Library digital archive (龍谷蔵)."""

    site_name = "龍谷大學圖書館 (Ryukoku)"
    site_id = "ryukoku"
    site_domains = ["da.library.ryukoku.ac.jp"]

    manifest_url_template = "https://da.library.ryukoku.ac.jp/iiif/{book_id}/1/manifest.json"

    default_headers = {"Referer": "https://da.library.ryukoku.ac.jp/"}

    def extract_book_id(self, url: str) -> str:
        # /iiif/{id}/{vol}/manifest.json
        m = re.search(r'/iiif/(\d+)/', url)
        if m:
            return m.group(1)
        # item page /page/{id}
        m = re.search(r'/page/(\d+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Ryukoku item id from URL: {url}")
