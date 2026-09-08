# 牛津大学博德利图书馆 (Bodleian Libraries) Adapter
# https://digital.bodleian.ox.ac.uk/
#
# Standard IIIF Presentation 2.0. Object pages live on digital.bodleian.ox.ac.uk;
# manifests are served from iiif.bodleian.ox.ac.uk.
#
# URL patterns:
#   - Object page:    https://digital.bodleian.ox.ac.uk/objects/{uuid}/
#   - IIIF manifest:  https://iiif.bodleian.ox.ac.uk/iiif/manifest/{uuid}.json

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


_UUID_RE = re.compile(
    r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
    re.IGNORECASE,
)


@AdapterRegistry.register
class BodleianAdapter(BaseIIIFAdapter):
    """Adapter for the Bodleian Libraries (University of Oxford) digital collections.

    One of Britain's oldest libraries; 2,000+ Chinese digitized items, all served
    via standard IIIF v2 manifests.
    """

    site_name = "牛津大学博德利图书馆 (Bodleian)"
    site_id = "bodleian"
    site_domains = ["digital.bodleian.ox.ac.uk", "iiif.bodleian.ox.ac.uk"]

    manifest_url_template = "https://iiif.bodleian.ox.ac.uk/iiif/manifest/{book_id}.json"

    def extract_book_id(self, url: str) -> str:
        """Extract the object UUID from an object-page or manifest URL."""
        m = _UUID_RE.search(url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Bodleian object UUID from URL: {url}")
