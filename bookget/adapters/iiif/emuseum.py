# e国宝 (e-Museum) Adapter
# https://emuseum.nich.go.jp/
#
# National treasures & important cultural properties of Japan's four national
# museums + Nara research institute. Standard IIIF Presentation 2.0.
#
# The detail page params combine into a 12-digit contentsID, from which the
# manifest URL is built (verified in-browser across several items):
#   contentsID = content_base_id + pad3(content_part_id) + pad3(content_pict_id)
#   manifest   = https://emuseum.nich.go.jp/iiifapi/{contentsID}/manifest.json
#
# URL patterns:
#   - Detail page:   https://emuseum.nich.go.jp/detail?content_base_id={B}&content_part_id={P}&content_pict_id={C}
#   - IIIF manifest: https://emuseum.nich.go.jp/iiifapi/{contentsID}/manifest.json

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class EMuseumAdapter(BaseIIIFAdapter):
    """Adapter for e国宝 / e-Museum (emuseum.nich.go.jp)."""

    site_name = "e国宝 (e-Museum)"
    site_id = "emuseum"
    site_domains = ["emuseum.nich.go.jp"]

    manifest_url_template = "https://emuseum.nich.go.jp/iiifapi/{book_id}/manifest.json"

    default_headers = {"Referer": "https://emuseum.nich.go.jp/"}

    def extract_book_id(self, url: str) -> str:
        """Build the 12-digit contentsID from a detail URL, or read it from a
        direct iiifapi/manifest URL."""
        # Direct manifest / api URL: /iiifapi/{contentsID}/manifest.json
        m = re.search(r'/iiifapi/(\d+)/manifest', url)
        if m:
            return m.group(1)

        base = re.search(r'content_base_id=(\d+)', url)
        if base:
            def part(name: str) -> str:
                mm = re.search(name + r'=(\d+)', url)
                return f"{int(mm.group(1)):03d}" if mm else "000"
            return f"{base.group(1)}{part('content_part_id')}{part('content_pict_id')}"

        raise MetadataExtractionError(
            f"Could not extract e-Museum contentsID from URL: {url}")
