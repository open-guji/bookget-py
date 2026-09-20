"""Offline tests for the IDP (International Dunhuang Programme) adapter.

The trap this adapter has to avoid: `uid` in an IDP URL is a search-session
token, not an item id. Measured on idp.bbaw.de, a URL carrying only the uid
returns a *different* item (Or.8210/S.1) with HTTP 200 — so rebuilding the
item URL from the uid downloads the wrong scroll without any error.
"""

import pytest

from bookget.adapters.registry import AdapterRegistry
from bookget.adapters.other.idp import IDPAdapter
from bookget.exceptions import MetadataExtractionError

BERLIN = ("http://idp.bbaw.de/database/oo_scroll_h.a4d"
          "?uid=5475972796;bst=1;recnum=69129;index=1;img=1")


class TestRouting:
    def test_idp_mirror_beats_the_british_library_adapter(self):
        """`bl.uk` is a substring of `idp.bl.uk`; the specific one must win."""
        adapter = AdapterRegistry.get_for_url(
            "http://idp.bl.uk/database/oo_scroll_h.a4d?uid=1;recnum=2")
        assert adapter is not None and adapter.site_id == "idp"

    def test_british_library_still_gets_its_own_urls(self):
        adapter = AdapterRegistry.get_for_url(
            "https://www.bl.uk/manuscripts/Viewer.aspx?ref=or_8210_p2")
        assert adapter is not None and adapter.site_id == "british_library"

    @pytest.mark.parametrize("host", [
        "idp.bl.uk", "idp.bnf.fr", "idp.bbaw.de", "idp.nlc.cn",
        "idp.korea.ac.kr", "idp.afc.ryukoku.ac.jp", "idp.orientalstudies.ru",
    ])
    def test_every_mirror_routes_to_idp(self, host):
        adapter = AdapterRegistry.get_for_url(
            f"http://{host}/database/oo_scroll_h.a4d?uid=1;recnum=2")
        assert adapter is not None and adapter.site_id == "idp"


class TestExtractBookId:
    def test_uid_and_recnum(self):
        assert IDPAdapter().extract_book_id(BERLIN) == "5475972796_69129"

    def test_pressmark_is_preferred_and_made_path_safe(self):
        adapter = IDPAdapter()
        book_id = adapter.extract_book_id(
            "http://idp.nlc.cn/database/oo_loader.a4d?pm=Or.8210/S.1")
        # "/" is a path separator and ":" is illegal on Windows.
        assert book_id == "Or.8210_S.1"

    def test_pressmark_with_percent_encoded_space(self):
        adapter = IDPAdapter()
        assert adapter.extract_book_id(
            "http://idp.bbaw.de/database/oo_loader.a4d?pm=Ch%201") == "Ch_1"

    def test_uid_without_recnum_is_refused(self):
        """Fetching it would silently return the wrong item."""
        with pytest.raises(MetadataExtractionError, match="recnum"):
            IDPAdapter().extract_book_id(
                "http://idp.bbaw.de/database/oo_scroll_h.a4d?uid=5475972796")

    def test_url_without_identifiers_is_refused(self):
        with pytest.raises(MetadataExtractionError):
            IDPAdapter().extract_book_id("http://idp.bbaw.de/about.a4d")


class TestUrlBuilding:
    def test_item_url_is_the_url_we_were_given(self):
        adapter = IDPAdapter()
        book_id = adapter.extract_book_id(BERLIN)
        assert adapter.item_url(book_id) == BERLIN

    def test_images_stay_on_the_mirror_the_item_came_from(self):
        adapter = IDPAdapter()
        book_id = adapter.extract_book_id(BERLIN)
        url = adapter.image_url(book_id, "99713")
        assert url.startswith("http://idp.bbaw.de/image_IDP.a4d?")
        assert "recnum=99713" in url and "imageType=_L" in url

    def test_pressmark_id_falls_back_to_the_loader(self):
        adapter = IDPAdapter()
        book_id = adapter.extract_book_id(
            "http://idp.bbaw.de/database/oo_loader.a4d?pm=Ch%201")
        adapter._source_urls.clear()  # e.g. a resumed download
        assert adapter.item_url(book_id) == (
            "http://idp.bbaw.de/database/oo_loader.a4d?pm=Ch_1")


class TestParseItemPage:
    PAGE = '''
        imageRecnum[0] = "99713";
        imagePMFolioTitles[0] = "Ch 1 ";
        imageRecnum[1] = "102602";
        imagePMFolioTitles[1] = "Ch 1 verso ";
    '''

    def test_reads_recnums_and_titles(self):
        recnums, folios = IDPAdapter.parse_item_page(self.PAGE)
        assert recnums == ["99713", "102602"]
        assert folios == ["Ch 1", "Ch 1 verso"]

    def test_empty_page(self):
        assert IDPAdapter.parse_item_page("<html></html>") == ([], [])


@pytest.mark.asyncio
class TestGetImageList:
    async def test_builds_resources_in_order(self):
        adapter = IDPAdapter()
        book_id = adapter.extract_book_id(BERLIN)
        adapter._pages[book_id] = ["99713", "102602"]
        images = await adapter.get_image_list(book_id)
        assert [i.order for i in images] == [1, 2]
        assert images[0].filename == "5475972796_69129_0001.jpg"
        assert "recnum=99713" in images[0].url

    async def test_item_without_images_raises(self):
        """Empty must not pass as a successful download of nothing."""
        adapter = IDPAdapter()
        book_id = adapter.extract_book_id(BERLIN)
        adapter._pages[book_id] = []
        with pytest.raises(MetadataExtractionError, match="没有图片记录"):
            await adapter.get_image_list(book_id)
