"""Offline tests for the U-Tokyo 漢籍善本 adapter."""

import pytest

from bookget.adapters.other.utokyo_shanben import UTokyoShanbenAdapter
from bookget.exceptions import MetadataExtractionError

ITEM = ("https://shanben.ioc.u-tokyo.ac.jp/main_p.php"
        "?nu=A000600&order=rn_no&no=00015&tim=hb")
PDF = "000772-十三經註疏崇禎中古虞毛氏汲古閣刊本-卷首.pdf"


class TestExtractBookId:
    def test_nu_and_no(self):
        assert UTokyoShanbenAdapter().extract_book_id(ITEM) == "A000600_00015"

    def test_nu_only(self):
        assert UTokyoShanbenAdapter().extract_book_id(
            "https://shanben.ioc.u-tokyo.ac.jp/main_p.php?nu=A000500") == "A000500"

    def test_url_without_nu(self):
        with pytest.raises(MetadataExtractionError, match="nu"):
            UTokyoShanbenAdapter().extract_book_id(
                "https://shanben.ioc.u-tokyo.ac.jp/list.php")


class TestParseItemPage:
    def test_title_and_pdfs(self):
        html = (f'<title>十三經註疏　崇禎中古虞毛氏汲古閣刊本</title>'
                f'<a href="pdf/{PDF}">PDF</a>')
        title, pdfs = UTokyoShanbenAdapter.parse_item_page(html)
        # The ideographic space becomes a plain one so the title is searchable.
        assert title == "十三經註疏 崇禎中古虞毛氏汲古閣刊本"
        assert pdfs == [PDF]

    def test_cover_only_record_has_no_pdf(self):
        _, pdfs = UTokyoShanbenAdapter.parse_item_page(
            '<title>x</title><img src="file/cover/1200/A000500.jpg">')
        assert pdfs == []


class TestUrls:
    def test_item_url_is_the_caller_url(self):
        adapter = UTokyoShanbenAdapter()
        assert adapter.item_url(adapter.extract_book_id(ITEM)) == ITEM

    def test_item_url_rebuilt_from_id(self):
        adapter = UTokyoShanbenAdapter()
        assert adapter.item_url("A000600_00015") == (
            "https://shanben.ioc.u-tokyo.ac.jp/main_p.php"
            "?nu=A000600&order=rn_no&tim=hb&no=00015")

    def test_pdf_filename_is_percent_encoded(self):
        url = UTokyoShanbenAdapter().pdf_url(PDF)
        assert url.startswith("https://shanben.ioc.u-tokyo.ac.jp/pdf/")
        assert "%E5%8D%81" in url  # 十, encoded
        assert " " not in url


@pytest.mark.asyncio
class TestGetImageList:
    async def _adapter(self, html):
        adapter = UTokyoShanbenAdapter()

        async def fake_page(_book_id):
            return html

        adapter._fetch_item_page = fake_page
        return adapter

    async def test_returns_pdf_resources(self):
        adapter = await self._adapter(f'<title>x</title><a href="pdf/{PDF}">p</a>')
        resources = await adapter.get_image_list("A000600_00015")
        assert len(resources) == 1
        assert resources[0].resource_type.value == "pdf"
        assert resources[0].filename == "A000600_00015_01.pdf"

    async def test_cover_only_record_raises(self):
        adapter = await self._adapter("<title>x</title>")
        with pytest.raises(MetadataExtractionError, match="没有可下载的 PDF"):
            await adapter.get_image_list("A000500")
