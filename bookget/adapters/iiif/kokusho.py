# 国書データベース (NIJL Kokusho Database) Adapter
# https://kokusho.nijl.ac.jp/
#
# National Institute of Japanese Literature's union database of Japanese
# classical books — ~1.6M bibliographic records, large share with IIIF images.
# Standard IIIF Presentation 2.0; the manifest URL is a static template.
#
# URL patterns:
#   - Detail page:   https://kokusho.nijl.ac.jp/biblio/{BID}            (optionally /{page})
#   - Mirador viewer:https://kokusho.nijl.ac.jp/app/mirador/{BID}/1/1
#   - IIIF manifest: https://kokusho.nijl.ac.jp/biblio/{BID}/manifest
#   where {BID} is a numeric 書誌ID, e.g. "100250746".

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class KokushoAdapter(BaseIIIFAdapter):
    """Adapter for the NIJL Kokusho Database (国書データベース)."""

    site_name = "国書データベース (NIJL Kokusho)"
    site_id = "kokusho"
    site_domains = ["kokusho.nijl.ac.jp"]

    manifest_url_template = "https://kokusho.nijl.ac.jp/biblio/{book_id}/manifest"

    default_headers = {"Referer": "https://kokusho.nijl.ac.jp/"}

    def extract_book_id(self, url: str) -> str:
        """Extract the numeric 書誌ID (BID) from a detail/viewer/manifest URL."""
        # /biblio/{BID} (detail or .../manifest)
        m = re.search(r'/biblio/(\d+)', url)
        if m:
            return m.group(1)
        # /app/mirador/{BID}/...
        m = re.search(r'/mirador/(\d+)', url)
        if m:
            return m.group(1)
        # ?manifest=.../biblio/{BID}/manifest
        m = re.search(r'manifest=[^&]*?/biblio/(\d+)/manifest', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Kokusho BID from URL: {url}")
