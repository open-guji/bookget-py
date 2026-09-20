"""Offline tests for Princeton's two-identifier problem.

dpul.princeton.edu runs Spotlight and mints its own catalog ids; the IIIF
manifest lives on figgy under a different (UUID) id, named in the catalog
record. Treating the catalog id as the figgy id answers 404 for every DPUL
item, which is what this adapter used to do.
"""

import pytest

from bookget.adapters.iiif.princeton import PrincetonAdapter
from bookget.exceptions import MetadataExtractionError


class TestManifestUrl:
    def test_figgy_uuid_uses_the_template(self):
        adapter = PrincetonAdapter()
        uuid = "9939d0d2-8fe7-4c2b-9592-bbd3360a93ba"
        assert adapter.get_manifest_url(uuid) == (
            f"https://figgy.princeton.edu/concern/scanned_resources/{uuid}/manifest")

    def test_resolved_url_wins_over_the_template(self):
        adapter = PrincetonAdapter()
        adapter._manifest_urls["563061ad856c222cb3228b2804dd3922"] = "https://figgy/x/manifest"
        assert adapter.get_manifest_url(
            "563061ad856c222cb3228b2804dd3922") == "https://figgy/x/manifest"


@pytest.mark.asyncio
class TestDpulResolution:
    async def test_catalog_id_is_resolved_before_fetching(self):
        adapter = PrincetonAdapter()
        calls = []

        async def fake_resolve(book_id):
            calls.append(book_id)
            return "https://figgy.princeton.edu/concern/scanned_resources/real-id/manifest"

        async def fake_super(_book_id):
            return {"label": "ok"}

        adapter._resolve_dpul_manifest = fake_resolve
        # stand in for BaseIIIFAdapter.get_iiif_manifest
        import bookget.adapters.iiif.base_iiif as base
        original = base.BaseIIIFAdapter.get_iiif_manifest
        base.BaseIIIFAdapter.get_iiif_manifest = lambda self, b: fake_super(b)
        try:
            result = await adapter.get_iiif_manifest("563061ad856c222cb3228b2804dd3922")
        finally:
            base.BaseIIIFAdapter.get_iiif_manifest = original

        assert result == {"label": "ok"}
        assert calls == ["563061ad856c222cb3228b2804dd3922"]
        assert adapter._manifest_urls["563061ad856c222cb3228b2804dd3922"].endswith(
            "real-id/manifest")

    async def test_figgy_uuid_skips_resolution(self):
        adapter = PrincetonAdapter()

        async def fail_resolve(_book_id):
            raise AssertionError("should not resolve a figgy uuid")

        async def fake_super(_book_id):
            return {}

        adapter._resolve_dpul_manifest = fail_resolve
        import bookget.adapters.iiif.base_iiif as base
        original = base.BaseIIIFAdapter.get_iiif_manifest
        base.BaseIIIFAdapter.get_iiif_manifest = lambda self, b: fake_super(b)
        try:
            await adapter.get_iiif_manifest("9939d0d2-8fe7-4c2b-9592-bbd3360a93ba")
        finally:
            base.BaseIIIFAdapter.get_iiif_manifest = original

    async def test_record_without_manifest_field_says_so(self):
        adapter = PrincetonAdapter()

        class FakeResponse:
            status = 200

            def raise_for_status(self):
                pass

            async def json(self, content_type=None):
                return {"response": {"document": {"id": "x"}}}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        class FakeSession:
            def get(self, _url):
                return FakeResponse()

        async def fake_session():
            return FakeSession()

        adapter.get_session = fake_session
        with pytest.raises(MetadataExtractionError, match="没有 IIIF manifest"):
            await adapter._resolve_dpul_manifest("deadbeef" * 4)
