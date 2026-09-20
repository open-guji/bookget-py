"""Offline tests for the Nôm Foundation adapter."""

import pytest

from bookget.adapters.other.nomfoundation import NomFoundationAdapter
from bookget.exceptions import MetadataExtractionError

PAGE = '''
  <title>欽定詠史 &bull; Kh&acirc;m định vịnh sử &bull; Page 1</title>
  <img src="/site_media/nom/nlvnpf-0001/jpeg/nlvnpf-0001-001.jpg"
       usemap="#pagemap" ismap="ismap"/>
  <div>Page 1 of 5</div>
'''


class TestExtractBookId:
    @pytest.mark.parametrize("url", [
        "https://lib.nomfoundation.org/collection/1/volume/1001",
        "https://lib.nomfoundation.org/collection/1/volume/1001/page/3",
    ])
    def test_volume_and_page_urls(self, url):
        assert NomFoundationAdapter().extract_book_id(url) == "1_1001"

    def test_non_volume_url(self):
        with pytest.raises(MetadataExtractionError):
            NomFoundationAdapter().extract_book_id(
                "https://lib.nomfoundation.org/collection/1/")


class TestParsePage:
    def test_title_entities_are_unescaped(self):
        title, prefix, count = NomFoundationAdapter.parse_page(PAGE)
        assert title == "欽定詠史 • Khâm định vịnh sử"
        assert prefix == "nlvnpf-0001"
        assert count == 5

    def test_page_without_an_image(self):
        assert NomFoundationAdapter.parse_page("<title>x</title>") == ("x", "", 0)


class TestImageUrl:
    def test_uses_the_large_derivative(self):
        url = NomFoundationAdapter.image_url("nlvnpf-0001", 7)
        assert url == ("https://lib.nomfoundation.org/site_media/nom/"
                       "nlvnpf-0001/large/nlvnpf-0001-007.jpg")


@pytest.mark.asyncio
class TestGetImageList:
    async def _adapter(self, html, existing_tail=0):
        adapter = NomFoundationAdapter()
        seen = {"probes": 0}

        async def fake_fetch(_url):
            return html

        async def fake_exists(_url):
            seen["probes"] += 1
            return seen["probes"] <= existing_tail

        adapter._fetch = fake_fetch
        adapter._exists = fake_exists
        adapter._seen = seen
        return adapter

    async def test_counted_pages_only(self):
        adapter = await self._adapter(PAGE)
        images = await adapter.get_image_list("1_1")
        assert len(images) == 5
        assert images[0].filename == "nlvnpf-0001-001.jpg"

    async def test_picks_up_trailing_images_the_viewer_hides(self):
        """Volume 1/1 really has 8 images though the viewer says 5."""
        adapter = await self._adapter(PAGE, existing_tail=3)
        images = await adapter.get_image_list("1_1")
        assert len(images) == 8
        assert images[-1].url.endswith("nlvnpf-0001-008.jpg")

    async def test_tail_probe_is_bounded(self):
        adapter = await self._adapter(PAGE, existing_tail=999)
        images = await adapter.get_image_list("1_1")
        assert len(images) == 5 + 12  # _TAIL_PROBE_LIMIT

    async def test_volume_without_images_raises(self):
        adapter = await self._adapter("<title>x</title>")
        with pytest.raises(MetadataExtractionError, match="没有影像"):
            await adapter.get_image_list("1_1")
