# 东洋文库 (Toyo Bunko, via NII Digital Silk Road) Adapter
# https://dsr.nii.ac.jp/toyobunko/
#
# 日本最大亚洲研究图书馆，含丝绸之路贵重书。标准 IIIF Presentation 2.0，
# manifest 可由 item URL 直接推导：
#   item /toyobunko/{item}/{vol}/  →  /toyobunko/{item}/{vol}/manifest.json
#
# URL patterns:
#   - Item page:     https://dsr.nii.ac.jp/toyobunko/{item}/{vol}/        (如 XI-6-A-16/V-1)
#   - IIIF manifest: https://dsr.nii.ac.jp/toyobunko/{item}/{vol}/manifest.json

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class ToyoBunkoAdapter(BaseIIIFAdapter):
    """Adapter for Toyo Bunko on NII's Digital Silk Road (dsr.nii.ac.jp)."""

    site_name = "东洋文库 (Toyo Bunko / NII-DSR)"
    site_id = "toyobunko"
    site_domains = ["dsr.nii.ac.jp"]

    manifest_url_template = "https://dsr.nii.ac.jp/toyobunko/{book_id}/manifest.json"

    default_headers = {"Referer": "https://dsr.nii.ac.jp/"}

    def extract_book_id(self, url: str) -> str:
        """book_id = "{item}/{vol}", e.g. "XI-6-A-16/V-1"."""
        m = re.search(r'/toyobunko/(.+?)/manifest\.json', url)
        if m:
            return m.group(1)
        m = re.search(r'/toyobunko/([^?#]+?)/?$', url)
        if m and not m.group(1).startswith("iiif/"):
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Toyo Bunko id from URL: {url}")
