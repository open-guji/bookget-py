# 香港大学数字图书馆 (HKU Digital Repository) Adapter
# https://digitalrepository.lib.hku.hk/
#
# HKU Libraries' digital repository (Next.js front-end over a IIIF backend).
# Includes 馮平山圖書館善本書影像庫 (Fung Ping Shan rare books — Song/Yuan/Ming/Qing
# editions). Standard IIIF Presentation 2.0 served under /service/api/.
#
# URL patterns:
#   - Item page:     https://digitalrepository.lib.hku.hk/catalog/{id}   (id e.g. "6q188b14n")
#   - IIIF manifest: https://digitalrepository.lib.hku.hk/service/api/iiif/manifest/{id}
#
# NOTE: manifest URL pattern matches bookget app/hkulib.go and HKU's live
# /service/api base; not yet live-verified here (HKU IIIF gateway returned
# 502/504 at implementation time), so no live_urls entry yet — offline routing
# is covered. Verify with `pytest -m live` once HKU's service is responsive.

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class HKUAdapter(BaseIIIFAdapter):
    """Adapter for the HKU Libraries Digital Repository."""

    site_name = "香港大学数字图书馆 (HKU)"
    site_id = "hku"
    site_domains = ["digitalrepository.lib.hku.hk"]

    manifest_url_template = "https://digitalrepository.lib.hku.hk/service/api/iiif/manifest/{book_id}"

    default_headers = {"Referer": "https://digitalrepository.lib.hku.hk/"}

    def extract_book_id(self, url: str) -> str:
        """Extract the catalog id from an item page or manifest URL."""
        m = re.search(r'/service/api/iiif/manifest/([A-Za-z0-9._-]+)', url)
        if m:
            return m.group(1)
        m = re.search(r'/catalog/([A-Za-z0-9._-]+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract HKU catalog id from URL: {url}")
