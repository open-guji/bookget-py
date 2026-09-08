# 史密森尼学会 (Smithsonian Institution) Adapter
# https://www.si.edu/  (IIIF image server: ids.si.edu)
#
# Standard IIIF Presentation 2.0 served from ids.si.edu. Includes Freer|Sackler
# (National Museum of Asian Art) East-Asian holdings.
#
# URL patterns:
#   - IIIF manifest: https://ids.si.edu/ids/manifest/{IDSID}
#   where {IDSID} is e.g. "FS-F1904.61_006".
#
# Note: object pages (asia.si.edu/object/…) embed the IDS id as a
# `data-idsid` HTML attribute and would need a page scrape to resolve; this
# adapter handles the direct IIIF manifest / ids URL form.

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class SmithsonianAdapter(BaseIIIFAdapter):
    """Adapter for the Smithsonian Institution IIIF image server (ids.si.edu)."""

    site_name = "史密森尼学会 (Smithsonian)"
    site_id = "smithsonian"
    site_domains = ["ids.si.edu", "iiif.si.edu"]

    manifest_url_template = "https://ids.si.edu/ids/manifest/{book_id}"

    default_headers = {
        "Referer": "https://www.si.edu/",
        "Origin": "https://www.si.edu",
    }

    def extract_book_id(self, url: str) -> str:
        """Extract the IDS id from a manifest URL."""
        m = re.search(r'/manifest/([A-Za-z0-9._-]+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Smithsonian IDS id from URL: {url}")
