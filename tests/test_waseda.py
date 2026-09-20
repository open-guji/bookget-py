"""Offline tests for the Waseda kotenseki adapter."""

import pytest

from bookget.adapters.other.waseda import WasedaAdapter
from bookget.exceptions import MetadataExtractionError

BOOK_DIR_HTML = '''
  <a href="bunko01_01501_0001/bunko01_01501_0001.html">HTML</a>
  <a href="bunko01_01501_0001/bunko01_01501_0001.pdf">PDF</a>
  <a href="bunko01_01501_0002/bunko01_01501_0002.html">HTML</a>
  <a href="bunko01_01501_0002/bunko01_01501_0002.pdf">PDF</a>
'''

VOLUME_HTML = '''
  <a href="bunko01_01501_0001_p0002.jpg">2</a>
  <a href="bunko01_01501_0001_p0001.jpg">1</a>
  <a href="bunko01_01501_0001_p0002.jpg">2</a>
  <a href="bunko01_01501_0001_p0010.jpg">10</a>
'''


class TestExtractBookId:
    @pytest.mark.parametrize("url", [
        "https://www.wul.waseda.ac.jp/kotenseki/html/bunko01/bunko01_01501/index.html",
        "https://archive.wul.waseda.ac.jp/kosho/bunko01/bunko01_01501/",
    ])
    def test_catalogue_and_archive_urls(self, url):
        assert WasedaAdapter().extract_book_id(url) == "bunko01_01501"

    def test_non_item_url(self):
        with pytest.raises(MetadataExtractionError):
            WasedaAdapter().extract_book_id(
                "https://www.wul.waseda.ac.jp/kotenseki/index.html")


class TestPaths:
    def test_group_is_the_directory(self):
        assert WasedaAdapter.group_of("bunko01_01501") == "bunko01"
        assert WasedaAdapter.group_of("ab_03379") == "ab"

    def test_book_dir(self):
        assert WasedaAdapter().book_dir("bunko01_01501") == (
            "https://archive.wul.waseda.ac.jp/kosho/bunko01/bunko01_01501/")


class TestParsing:
    def test_fascicles_are_deduplicated(self):
        assert WasedaAdapter.parse_book_dir(BOOK_DIR_HTML) == [
            "bunko01_01501_0001", "bunko01_01501_0002"]

    def test_pages_are_deduplicated_and_ordered_by_number(self):
        """Each page is linked twice, and not in page order."""
        assert WasedaAdapter.parse_volume(VOLUME_HTML) == [
            "bunko01_01501_0001_p0001.jpg",
            "bunko01_01501_0001_p0002.jpg",
            "bunko01_01501_0001_p0010.jpg",
        ]

    def test_thumbnails_are_not_picked_up(self):
        assert WasedaAdapter.parse_volume(
            '<a href="bunko01_01501_0001_p0001s.jpg">1</a>') == []


@pytest.mark.asyncio
class TestGetImageList:
    async def _adapter(self, pages: dict):
        adapter = WasedaAdapter()

        async def fake_fetch(url):
            for key, html in pages.items():
                if url.endswith(key):
                    return html
            return ""

        adapter._fetch = fake_fetch
        return adapter

    async def test_flattens_every_fascicle(self):
        adapter = await self._adapter({
            "bunko01_01501/": BOOK_DIR_HTML,
            "bunko01_01501_0001.html": VOLUME_HTML,
            "bunko01_01501_0002.html": VOLUME_HTML.replace("_0001_", "_0002_"),
        })
        images = await adapter.get_image_list("bunko01_01501")
        assert len(images) == 6
        assert images[0].url.endswith(
            "bunko01_01501_0001/bunko01_01501_0001_p0001.jpg")
        assert images[3].url.endswith(
            "bunko01_01501_0002/bunko01_01501_0002_p0001.jpg")
        assert [i.order for i in images[:3]] == [1, 2, 3]

    async def test_book_without_fascicles_raises(self):
        adapter = await self._adapter({"bunko01_01501/": "<html></html>"})
        with pytest.raises(MetadataExtractionError, match="没有册"):
            await adapter.get_image_list("bunko01_01501")
