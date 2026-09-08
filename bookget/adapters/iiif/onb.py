# 奥地利国家图书馆 (Österreichische Nationalbibliothek / ONB) Adapter
# https://viewer.onb.ac.at/
#
# ONB 已从旧的 /OnbViewer/ 自定义查看器迁到新的 viewer.onb.ac.at，背后是标准
# IIIF Presentation v3（bookget app/onbdigital.go 的旧 imageData 接口已过时）。
# 含耶稣会汉籍 Sinica 等珍品。
#
# URL patterns:
#   - 新查看器:     https://viewer.onb.ac.at/{doc}
#   - 跳转提示页:   https://viewer.onb.ac.at/redirect-hinweis/{doc}
#   - 旧查看器:     https://digital.onb.ac.at/OnbViewer/viewer.faces?doc={doc}  (会跳转到新版)
#   - IIIF v3 清单: https://api.onb.ac.at/iiif/presentation/v3/manifest/{doc}
#   其中 {doc} 形如 "ABO_+Z201494000"（含字面 '+'）。

import re
from urllib.parse import unquote

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class ONBAdapter(BaseIIIFAdapter):
    """Adapter for the Austrian National Library (ONB) — IIIF v3."""

    site_name = "奥地利国家图书馆 (ONB)"
    site_id = "onb"
    site_domains = [
        "viewer.onb.ac.at",
        "digital.onb.ac.at",
        "api.onb.ac.at",
        "onb.digital",
    ]

    manifest_url_template = "https://api.onb.ac.at/iiif/presentation/v3/manifest/{book_id}"
    DEFAULT_IIIF_SIZE = "max"  # IIIF v3

    default_headers = {"Referer": "https://viewer.onb.ac.at/"}

    def extract_book_id(self, url: str) -> str:
        """Extract the ONB document id from any of its URL forms.

        Keeps the literal '+' in ids like "ABO_+Z201494000" (unquote turns
        %2B back into '+' and leaves a literal '+' unchanged)."""
        m = re.search(r'[?&]doc=([^&]+)', url)
        if m:
            return unquote(m.group(1))
        m = re.search(r'/manifest/([^/?#]+)', url)
        if m:
            return unquote(m.group(1))
        m = re.search(
            r'(?:viewer\.onb\.ac\.at|onb\.digital)/(?:redirect-hinweis/)?([^/?#]+)',
            url)
        if m:
            return unquote(m.group(1))
        raise MetadataExtractionError(
            f"Could not extract ONB document id from URL: {url}")
