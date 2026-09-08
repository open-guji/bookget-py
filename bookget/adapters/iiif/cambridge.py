# 剑桥大学数字图书馆 (Cambridge Digital Library, CUDL) Adapter
# https://cudl.lib.cam.ac.uk/
#
# Standard IIIF Presentation 2.0. Strong Chinese holdings (oracle bones,
# Dunhuang / Huizhou manuscripts, Song-onward rare books, rubbings).
#
# URL patterns:
#   - Viewer page:    https://cudl.lib.cam.ac.uk/view/{item_id}        (optionally /{page})
#   - IIIF manifest:  https://cudl.lib.cam.ac.uk/iiif/{item_id}
#   where {item_id} is e.g. "MS-NN-00002-00041".

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class CambridgeCUDLAdapter(BaseIIIFAdapter):
    """Adapter for the Cambridge Digital Library (CUDL)."""

    site_name = "剑桥大学数字图书馆 (CUDL)"
    site_id = "cambridge_cudl"
    site_domains = ["cudl.lib.cam.ac.uk"]

    manifest_url_template = "https://cudl.lib.cam.ac.uk/iiif/{book_id}"

    def extract_book_id(self, url: str) -> str:
        """Extract the CUDL item id from a viewer or manifest URL."""
        # /view/{id} or /view/{id}/{page}
        m = re.search(r'/view/([A-Za-z0-9._-]+)', url)
        if m:
            return m.group(1)
        # /iiif/{id}
        m = re.search(r'/iiif/([A-Za-z0-9._-]+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract CUDL item id from URL: {url}")
