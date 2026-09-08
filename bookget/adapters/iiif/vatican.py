# 梵蒂冈宗座图书馆 (Biblioteca Apostolica Vaticana / DigiVatlib) Adapter
# https://digi.vatlib.it/
#
# Standard IIIF Presentation 2.0. Includes Borgia/Pelliot Chinese & East-Asian
# manuscripts and Jesuit-era documents.
#
# URL patterns:
#   - Viewer page:    https://digi.vatlib.it/view/{shelfmark}
#   - IIIF manifest:  https://digi.vatlib.it/iiif/{shelfmark}/manifest.json
#   where {shelfmark} is e.g. "MSS_Vat.lat.3773" (may contain dots).

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class VaticanAdapter(BaseIIIFAdapter):
    """Adapter for the Vatican Library digital collections (DigiVatlib)."""

    site_name = "梵蒂冈宗座图书馆 (DigiVatlib)"
    site_id = "vatican"
    site_domains = ["digi.vatlib.it"]

    manifest_url_template = "https://digi.vatlib.it/iiif/{book_id}/manifest.json"

    def extract_book_id(self, url: str) -> str:
        """Extract the shelfmark identifier from a viewer or manifest URL."""
        # /iiif/{id}/manifest.json
        m = re.search(r'/iiif/([^/]+)/manifest', url)
        if m:
            return m.group(1)
        # /view/{id}
        m = re.search(r'/view/([^/?#]+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Vatican shelfmark from URL: {url}")
