# 国立歴史民俗博物館 khirin-a Adapter
# https://khirin-a.rekihaku.ac.jp/
#
# Open IIIF archive of the National Museum of Japanese History (national-treasure
# Song-edition books, woodblock prints 錦絵, old documents). IIIF Presentation 2.0,
# but the manifest URL is per-collection and NOT derivable from the item id, so it
# is scraped from the item page HTML (the Universal Viewer reference
# `manifest=https://.../manifests/{coll}/{ID}.json`, which is present in the
# server-rendered HTML — no browser needed).
#
# URL patterns:
#   - Item page:     https://khirin-a.rekihaku.ac.jp/{collection}/{id}   (e.g. nmjh_nishikie/h-22-1-1-1)
#                    or older single-segment https://khirin-a.rekihaku.ac.jp/{id}
#   - IIIF manifest: e.g. https://khirin-a.rekihaku.ac.jp/manifests/nishikie/H-22-1-1-1.json
#                    (varies by collection; resolved by scraping the item page)

import re
from typing import Optional

from .base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...logger import logger
from ...exceptions import MetadataExtractionError

# manifest reference embedded in the item page (UV viewer hash / config)
_MANIFEST_RE = re.compile(r'manifest=(https?://[^"\'\s&]+\.json)')
_MANIFEST_FALLBACK_RE = re.compile(
    r'(https?://khirin-a\.rekihaku\.ac\.jp/[^"\'\s]+\.json)')

# Non-item top-level paths to ignore.
_NAV = {"database", "news", "exhibition", "libraries", "search", "about", "iiif"}


@AdapterRegistry.register
class KhirinAdapter(BaseIIIFAdapter):
    """Adapter for the National Museum of Japanese History khirin-a IIIF archive.

    The manifest URL is not derivable; it is scraped from the item page HTML.
    """

    site_name = "国立歴史民俗博物館 (khirin-a)"
    site_id = "khirin"
    site_domains = ["khirin-a.rekihaku.ac.jp"]

    BASE = "https://khirin-a.rekihaku.ac.jp"
    default_headers = {"Referer": "https://khirin-a.rekihaku.ac.jp/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._manifest_cache: dict[str, str] = {}

    def extract_book_id(self, url: str) -> str:
        """Return the item path (e.g. "nmjh_nishikie/h-22-1-1-1") or a direct
        manifest .json path as the book id."""
        m = re.search(r'rekihaku\.ac\.jp/(.+)$', url)
        if not m:
            raise MetadataExtractionError(
                f"Could not extract khirin item id from URL: {url}")
        path = m.group(1).split('#')[0].split('?')[0].strip('/')
        if not path or path.split('/')[0] in _NAV and not path.endswith('.json'):
            # allow /manifests/... json (starts with 'manifests' which isn't nav)
            if not path.endswith('.json'):
                raise MetadataExtractionError(
                    f"Not a khirin item URL: {url}")
        return path

    def get_manifest_url(self, book_id: str) -> str:
        """Return the resolved manifest URL (after get_iiif_manifest), or a
        direct manifest URL when the book id already points at a .json."""
        if book_id.endswith('.json'):
            return f"{self.BASE}/{book_id}"
        return self._manifest_cache.get(book_id, "")

    async def _resolve_manifest_url(self, book_id: str) -> str:
        if book_id.endswith('.json'):
            return f"{self.BASE}/{book_id}"
        if book_id in self._manifest_cache:
            return self._manifest_cache[book_id]

        item_url = f"{self.BASE}/{book_id}"
        session = await self.get_session()
        async with session.get(item_url, headers=self.get_headers(item_url)) as r:
            r.raise_for_status()
            html = await r.text()

        m = _MANIFEST_RE.search(html) or _MANIFEST_FALLBACK_RE.search(html)
        if not m:
            raise MetadataExtractionError(
                f"No IIIF manifest found in khirin item page: {item_url}")
        manifest_url = m.group(1)
        self._manifest_cache[book_id] = manifest_url
        logger.debug(f"[khirin] resolved manifest: {manifest_url}")
        return manifest_url

    async def get_iiif_manifest(self, book_id: str) -> Optional[dict]:
        """Scrape the manifest URL from the item page, then fetch it."""
        url = await self._resolve_manifest_url(book_id)
        session = await self.get_session()
        async with session.get(url, headers=self.get_headers(url)) as r:
            r.raise_for_status()
            return await r.json()
