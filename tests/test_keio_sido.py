"""Offline tests for the Keio Shido Bunko adapter."""

import pytest

from bookget.adapters.registry import AdapterRegistry
from bookget.adapters.iiif.keio_sido import KeioSidoAdapter
from bookget.exceptions import MetadataExtractionError

MANIFEST = ("https://db2.sido.keio.ac.jp/iiif/manifests/kanseki/"
            "006754/006754-001/manifest.json")


class TestRouting:
    def test_item_page_routes_here(self):
        adapter = AdapterRegistry.get_for_url(
            "https://db2.sido.keio.ac.jp/kanseki/bib_frame?id=006754")
        assert adapter is not None and adapter.site_id == "keio_sido"

    def test_does_not_steal_the_other_keio_site(self):
        adapter = AdapterRegistry.get_for_url(
            "https://dcollections.lib.keio.ac.jp/ja/kanseki/110x-24-1")
        assert adapter is not None and adapter.site_id == "keio"


class TestExtractBookId:
    @pytest.mark.parametrize("url", [
        "https://db2.sido.keio.ac.jp/kanseki/bib_frame?id=006754",
        "https://db2.sido.keio.ac.jp/kanseki/bib_image?id=006754",
    ])
    def test_from_item_page(self, url):
        assert KeioSidoAdapter().extract_book_id(url) == "006754"

    def test_manifest_url_also_seeds_the_cache(self):
        """A manifest URL carries the folio, so no page fetch is needed."""
        adapter = KeioSidoAdapter()
        assert adapter.extract_book_id(MANIFEST) == "006754"
        assert adapter.get_manifest_url("006754") == MANIFEST

    def test_url_without_id(self):
        with pytest.raises(MetadataExtractionError, match="id"):
            KeioSidoAdapter().extract_book_id(
                "https://db2.sido.keio.ac.jp/kanseki/")


@pytest.mark.asyncio
class TestResolveManifest:
    async def _adapter_returning(self, html):
        adapter = KeioSidoAdapter()

        class FakeResponse:
            def raise_for_status(self):
                pass

            async def text(self):
                return html

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        class FakeSession:
            def get(self, _url, headers=None):
                return FakeResponse()

        async def fake_session():
            return FakeSession()

        adapter.get_session = fake_session
        return adapter

    async def test_scrapes_the_manifest_url(self):
        adapter = await self._adapter_returning(f'<a href="{MANIFEST}">x</a>')
        assert await adapter._resolve_manifest_url("006754") == MANIFEST

    async def test_record_without_images_says_so(self):
        adapter = await self._adapter_returning("<html>書誌のみ</html>")
        with pytest.raises(MetadataExtractionError, match="没有 IIIF manifest"):
            await adapter._resolve_manifest_url("006754")

    async def test_multiple_manifests_takes_the_first_deterministically(self):
        """Order must not depend on where they sat in the HTML."""
        second = MANIFEST.replace("006754-001", "006754-002")
        adapter = await self._adapter_returning(f'{second} {MANIFEST}')
        assert await adapter._resolve_manifest_url("006754") == MANIFEST
