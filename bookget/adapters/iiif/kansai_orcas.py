# 関西大学 KU-ORCAS デジタルアーカイブ (Kansai University, KU-ORCAS)
# https://www.iiif.ku-orcas.kansai-u.ac.jp/
#
# 泊園文庫（漢籍）・増田渉文庫・長谷川コレクション 等。IIIF Presentation 2.0,
# and unusually for a Japanese archive the manifest path is derivable from the
# item URL, so no page scraping is needed:
#   item     https://www.iiif.ku-orcas.kansai-u.ac.jp/books/{id}
#   manifest https://www.iiif.ku-orcas.kansai-u.ac.jp/iiif/books/{id}/manifest.json

import re

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError

_ID_RE = re.compile(r'/(?:iiif/)?books/([A-Za-z0-9_-]+)')


@AdapterRegistry.register
class KansaiOrcasAdapter(BaseIIIFAdapter):
    """Adapter for Kansai University's KU-ORCAS digital archive."""

    site_name = "関西大学 KU-ORCAS (Kansai)"
    site_id = "kansai_orcas"
    site_domains = ["iiif.ku-orcas.kansai-u.ac.jp"]

    BASE = "https://www.iiif.ku-orcas.kansai-u.ac.jp"
    default_headers = {"Referer": "https://www.iiif.ku-orcas.kansai-u.ac.jp/"}

    manifest_url_template = (
        "https://www.iiif.ku-orcas.kansai-u.ac.jp/iiif/books/{book_id}/manifest.json")

    def extract_book_id(self, url: str) -> str:
        # Viewer links carry the manifest as a query parameter:
        #   .../iiif-curation-viewer/index.html?manifest=.../books/{id}/manifest.json
        match = _ID_RE.search(url)
        if match:
            return match.group(1)
        raise MetadataExtractionError(
            f"KU-ORCAS 地址里取不到条目 id：{url}\n"
            f"（条目地址形如 /books/002720833）")
