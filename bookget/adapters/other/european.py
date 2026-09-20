# European Digital Library Adapters

import re

from ..iiif.base_iiif import BaseIIIFAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError


@AdapterRegistry.register
class BnFGallicaAdapter(BaseIIIFAdapter):
    """
    Adapter for Bibliothèque nationale de France - Gallica.
    
    Gallica is one of the largest digital libraries in the world,
    holding significant Chinese manuscript collections.
    
    URL patterns:
    - Detail: https://gallica.bnf.fr/ark:/12148/{ark_id}
    - IIIF Manifest: https://gallica.bnf.fr/iiif/ark:/12148/{ark_id}/manifest.json
    """

    site_name = "法国国家图书馆 (BnF Gallica)"
    site_id = "bnf_gallica"
    site_domains = ["gallica.bnf.fr"]

    supports_iiif = True

    def extract_book_id(self, url: str) -> str:
        """Extract ARK identifier from BnF URL."""
        match = re.search(r'ark:/12148/([a-z0-9]+)', url)
        if match:
            return match.group(1)
        raise ValueError(f"Could not extract ARK ID from URL: {url}")

    def get_headers(self, url: str = None) -> dict:
        """Add Referer to Gallica requests."""
        headers = super().get_headers(url)
        headers["Referer"] = "https://gallica.bnf.fr/"
        return headers

    def get_manifest_url(self, book_id: str) -> str:
        return f"https://gallica.bnf.fr/iiif/ark:/12148/{book_id}/manifest.json"


@AdapterRegistry.register
class BritishLibraryAdapter(BaseIIIFAdapter):
    """
    Adapter for British Library.
    
    Holds important Chinese and Oriental manuscript collections.
    
    URL patterns:
    - Viewer: https://www.bl.uk/manuscripts/Viewer.aspx?ref={manuscript_ref}
    - IIIF: varies by collection
    """

    site_name = "大英图书馆 (British Library)"
    site_id = "british_library"
    site_domains = ["bl.uk", "www.bl.uk"]

    supports_iiif = True

    def extract_book_id(self, url: str) -> str:
        """Extract manuscript reference from BL URL."""
        match = re.search(r'ref=([^&]+)', url)
        if match:
            return match.group(1)

        # Try other patterns
        match = re.search(r'/items/([^/]+)', url)
        if match:
            return match.group(1)

        raise ValueError(f"Could not extract reference from URL: {url}")

    def get_manifest_url(self, book_id: str) -> str:
        # BL IIIF manifests are at different locations depending on collection
        return f"https://api.bl.uk/metadata/iiif/{book_id}/manifest.json"

    async def get_iiif_manifest(self, book_id: str):
        """Fetch the manifest, or explain why this adapter cannot work.

        api.bl.uk — the only host this adapter talks to — no longer exists:
        it is NXDOMAIN at Google's public resolver as well as here (checked
        2026-09-20), and the old /manuscripts/Viewer.aspx entry point now
        307s to a generic collection page. Without that, every request fails
        as a bare DNS error, which reads like a local network problem.
        """
        try:
            return await super().get_iiif_manifest(book_id)
        except MetadataExtractionError as e:
            raise MetadataExtractionError(
                f"[{self.site_id}] 大英图书馆的 IIIF 接口主机 api.bl.uk 已下线"
                f"（DNS 全球 NXDOMAIN，2026-09-20 核实），旧的 "
                f"/manuscripts/Viewer.aspx 阅览器也已跳转到通用页面。\n"
                f"该适配器目前不可用，需按 BL 重建后的新接口重做。\n"
                f"原始错误：{e}"
            ) from e


@AdapterRegistry.register
class BayerischeStaatsbibliothekAdapter(BaseIIIFAdapter):
    """
    Adapter for Bayerische Staatsbibliothek (BSB) - Munich.
    
    One of the most important collections of Chinese rare books in Europe.
    
    URL patterns:
    - Detail: https://www.digitale-sammlungen.de/de/view/{bsb_id}
    - IIIF: https://api.digitale-sammlungen.de/iiif/presentation/v2/{bsb_id}/manifest
    """

    site_name = "巴伐利亚州立图书馆 (BSB)"
    site_id = "bsb"
    site_domains = ["digitale-sammlungen.de", "www.digitale-sammlungen.de"]

    supports_iiif = True

    def extract_book_id(self, url: str) -> str:
        """Extract BSB ID from URL."""
        match = re.search(r'/(bsb\d+)', url)
        if match:
            return match.group(1)

        match = re.search(r'/view/([^/?]+)', url)
        if match:
            return match.group(1)

        raise ValueError(f"Could not extract BSB ID from URL: {url}")

    def get_manifest_url(self, book_id: str) -> str:
        return f"https://api.digitale-sammlungen.de/iiif/presentation/v2/{book_id}/manifest"
