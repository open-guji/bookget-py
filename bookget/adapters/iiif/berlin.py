# 柏林国立图书馆 (Staatsbibliothek zu Berlin) Adapter
# https://digital.staatsbibliothek-berlin.de/
#
# Standard IIIF Presentation 2.0. ~1900 digitized Chinese rare books plus large
# Oriental-manuscript holdings. Works are identified by a PPN; manifests are
# served from content.staatsbibliothek-berlin.de.
#
# URL patterns:
#   - Viewer page:   https://digital.staatsbibliothek-berlin.de/werkansicht?PPN={PPN}&PHYSID=...
#   - IIIF manifest: https://content.staatsbibliothek-berlin.de/dc/{PPN}/manifest
#   where {PPN} is e.g. "PPN610311271".

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class BerlinSBBAdapter(BaseIIIFAdapter):
    """Adapter for the Staatsbibliothek zu Berlin digitized collections."""

    site_name = "柏林国立图书馆 (Staatsbibliothek zu Berlin)"
    site_id = "berlin_sbb"
    site_domains = [
        "digital.staatsbibliothek-berlin.de",
        "content.staatsbibliothek-berlin.de",
    ]

    manifest_url_template = "https://content.staatsbibliothek-berlin.de/dc/{book_id}/manifest"

    # Image tiles on content.staatsbibliothek-berlin.de check Origin/Referer.
    default_headers = {
        "Referer": "https://digital.staatsbibliothek-berlin.de/",
        "Origin": "https://digital.staatsbibliothek-berlin.de",
    }

    def extract_book_id(self, url: str) -> str:
        """Extract the PPN identifier from a viewer or manifest URL."""
        # ?PPN=PPN610311271 (the value itself carries the "PPN" prefix)
        m = re.search(r'[?&]PPN=([A-Za-z0-9_-]+)', url)
        if m:
            return m.group(1)
        # /dc/{PPN}/manifest
        m = re.search(r'/dc/([A-Za-z0-9_-]+)/manifest', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Berlin PPN from URL: {url}")
