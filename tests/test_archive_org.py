"""Offline tests for the archive.org adapter's page-list logic.

These cover the failure that made the adapter report a successful download of
zero images: it assumed every item ships `{identifier}_tif.zip` and carries an
`imagecount`, which is false for JP2-only items and for items whose derivative
is not named after the identifier.
"""

import pytest

from bookget.adapters.other.archive_org import ArchiveOrgAdapter
from bookget.exceptions import MetadataExtractionError


def _files(*names):
    return [{"name": n} for n in names]


class TestFindImageDerivative:
    def test_prefers_jp2_over_tif(self):
        found = ArchiveOrgAdapter._find_image_derivative(
            _files("foo_tif.zip", "foo_jp2.zip"), "foo")
        assert found == ("foo", "jp2")

    def test_falls_back_to_tif(self):
        found = ArchiveOrgAdapter._find_image_derivative(
            _files("foo_tif.zip"), "foo")
        assert found == ("foo", "tif")

    def test_derivative_not_named_after_identifier(self):
        # Real item: in.ernet.dli.2015.282
        found = ArchiveOrgAdapter._find_image_derivative(
            _files("2015.282.Tory-Lives-From-Falkland-To-Disraeli_jp2.zip"),
            "in.ernet.dli.2015.282")
        assert found == ("2015.282.Tory-Lives-From-Falkland-To-Disraeli", "jp2")

    def test_prefers_the_stack_named_after_the_identifier(self):
        # Real item nybc210940 ships both; `_orig_tif.zip` sorts first in the
        # file list but is not the derivative BookReader serves.
        found = ArchiveOrgAdapter._find_image_derivative(
            _files("nybc210940_orig_tif.zip", "nybc210940_tif.zip"),
            "nybc210940")
        assert found == ("nybc210940", "tif")

    def test_no_image_stack(self):
        found = ArchiveOrgAdapter._find_image_derivative(
            _files("foo.pdf", "foo_meta.xml", "foo_archive.torrent"), "foo")
        assert found is None


class TestResourcesFromJSIA:
    def test_flattens_spreads_and_keeps_leaf_order(self):
        payload = {"data": {"brOptions": {"data": [
            [{"uri": "https://x/1", "leafNum": 1},
             {"uri": "https://x/2", "leafNum": 2}],
            [{"uri": "https://x/3", "leafNum": 3}],
        ]}}}
        res = ArchiveOrgAdapter._resources_from_jsia("bk", payload)
        assert [r.url for r in res] == ["https://x/1", "https://x/2", "https://x/3"]
        assert [r.order for r in res] == [1, 2, 3]
        assert res[0].filename == "bk_0001.jpg"

    def test_skips_pages_without_uri(self):
        payload = {"data": {"brOptions": {"data": [
            [{"leafNum": 1}, {"uri": "https://x/2", "leafNum": 2}],
        ]}}}
        res = ArchiveOrgAdapter._resources_from_jsia("bk", payload)
        assert len(res) == 1 and res[0].url == "https://x/2"

    def test_empty_payload_is_empty_list(self):
        assert ArchiveOrgAdapter._resources_from_jsia("bk", {}) == []


class TestResourcesFromTemplate:
    def test_uses_the_derivative_prefix_and_kind(self):
        res = ArchiveOrgAdapter._resources_from_template(
            "bk", "ia1.us.archive.org", "/3/items/bk", "odd-prefix", "jp2", 2)
        assert len(res) == 2
        assert "zip=/3/items/bk/odd-prefix_jp2.zip" in res[0].url
        assert "file=odd-prefix_jp2/odd-prefix_0001.jp2" in res[0].url
        assert "id=bk" in res[0].url


@pytest.mark.asyncio
class TestGetImageListFailures:
    async def _adapter(self, metadata, pages=None):
        adapter = ArchiveOrgAdapter()

        async def fake_metadata(_identifier):
            return metadata

        async def fake_pages(*_args, **_kwargs):
            return pages or []

        adapter._fetch_ia_metadata = fake_metadata
        adapter._pages_from_bookreader = fake_pages
        return adapter

    async def test_raises_instead_of_returning_empty(self):
        """An item with no image stack must fail loudly.

        Returning [] here is what let a download of nothing be reported as a
        success.
        """
        adapter = await self._adapter({
            "server": "ia1.us.archive.org",
            "dir": "/3/items/bk",
            "metadata": {},
            "files": _files("bk.mp3", "bk_meta.xml"),
        })
        with pytest.raises(MetadataExtractionError, match="no pages"):
            await adapter.get_image_list("bk")

    async def test_raises_when_metadata_is_empty(self):
        adapter = await self._adapter({})
        with pytest.raises(MetadataExtractionError):
            await adapter.get_image_list("bk")

    async def test_raises_when_item_has_no_server(self):
        adapter = await self._adapter({"metadata": {}, "files": []})
        with pytest.raises(MetadataExtractionError, match="server/dir"):
            await adapter.get_image_list("bk")

    async def test_falls_back_to_template_when_bookreader_is_silent(self):
        adapter = await self._adapter({
            "server": "ia1.us.archive.org",
            "dir": "/3/items/bk",
            "metadata": {"imagecount": "3"},
            "files": _files("bk_jp2.zip"),
        })
        res = await adapter.get_image_list("bk")
        assert len(res) == 3
        assert "bk_jp2/bk_0001.jp2" in res[0].url
