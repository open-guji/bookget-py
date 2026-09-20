"""Offline tests for the Yonezawa City Library adapter."""

import pytest

from bookget.adapters.other.yonezawa import YonezawaAdapter
from bookget.exceptions import MetadataExtractionError

VIEWER = '''
  <script>var dir = 'data/AA001/'; var page = 1;</script>
  <select>
    <option value="AA001001,059">1</option>
    <option value="AA001002,043">2</option>
  </select>
'''


class TestExtractBookId:
    @pytest.mark.parametrize("url", [
        "https://www.library.yonezawa.yamagata.jp/dg/AA001.html",
        "https://www.library.yonezawa.yamagata.jp/dg/AA001_view.html",
        "http://www.library.yonezawa.yamagata.jp/dg/aa001.html",
    ])
    def test_item_and_viewer_urls(self, url):
        assert YonezawaAdapter().extract_book_id(url) == "AA001"

    def test_non_item_url(self):
        with pytest.raises(MetadataExtractionError):
            YonezawaAdapter().extract_book_id(
                "https://www.library.yonezawa.yamagata.jp/dg/guide.html")


class TestParseViewer:
    def test_reads_dir_and_fascicles(self):
        directory, volumes = YonezawaAdapter.parse_viewer(VIEWER)
        assert directory == "data/AA001/"
        assert volumes == [("AA001001", 59), ("AA001002", 43)]

    def test_page_without_the_viewer_script(self):
        assert YonezawaAdapter.parse_viewer("<html></html>") == ("", [])


class TestImageUrl:
    def test_fascicle_folder_is_the_last_three_digits(self):
        url = YonezawaAdapter().image_url("data/AA001/", "AA001002", 7)
        assert url == ("https://www.library.yonezawa.yamagata.jp/dg/"
                       "data/AA001/002/AA001002_007.jpg")


@pytest.mark.asyncio
class TestGetImageList:
    async def _adapter(self, html):
        adapter = YonezawaAdapter()

        async def fake_fetch(_url):
            return html

        adapter._fetch = fake_fetch
        return adapter

    async def test_flattens_every_fascicle(self):
        adapter = await self._adapter(VIEWER)
        images = await adapter.get_image_list("AA001")
        assert len(images) == 59 + 43
        assert images[0].url.endswith("data/AA001/001/AA001001_001.jpg")
        assert images[58].url.endswith("data/AA001/001/AA001001_059.jpg")
        # the next one crosses into the second fascicle
        assert images[59].url.endswith("data/AA001/002/AA001002_001.jpg")
        assert [i.order for i in images[:3]] == [1, 2, 3]

    async def test_changed_page_structure_raises(self):
        adapter = await self._adapter("<html>改版了</html>")
        with pytest.raises(MetadataExtractionError, match="没有册目录"):
            await adapter.get_image_list("AA001")
