# Tests for site adapters

import pytest
from bookget.adapters import AdapterRegistry, get_adapter
from bookget.adapters.base import BaseSiteAdapter


class TestAdapterRegistry:
    """Tests for adapter registry."""
    
    def test_list_adapters(self):
        adapters = AdapterRegistry.list_adapters()
        assert len(adapters) >= 10  # We have at least 14 adapters
        
        # Check structure
        for adapter in adapters:
            assert "id" in adapter
            assert "name" in adapter
            assert "domains" in adapter
    
    def test_get_for_url_nlc(self):
        adapter_class = AdapterRegistry.get_for_url("https://guji.nlc.cn/book/123")
        assert adapter_class is not None
        assert adapter_class.site_id == "nlc_guji"
    
    def test_get_for_url_harvard(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990080"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "harvard"
    
    def test_get_for_url_ndl(self):
        adapter_class = AdapterRegistry.get_for_url("https://dl.ndl.go.jp/pid/2592420")
        assert adapter_class is not None
        assert adapter_class.site_id == "ndl"
    
    def test_get_for_url_ctext(self):
        adapter_class = AdapterRegistry.get_for_url("https://ctext.org/analects")
        assert adapter_class is not None
        assert adapter_class.site_id == "ctext"
    
    def test_get_for_url_shidianguji(self):
        adapter_class = AdapterRegistry.get_for_url("https://www.shidianguji.com/book/123")
        assert adapter_class is not None
        assert adapter_class.site_id == "shidianguji"
    
    def test_get_for_url_bnf(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://gallica.bnf.fr/ark:/12148/btv1b9006423x"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "bnf_gallica"
    
    def test_get_for_url_unknown(self):
        adapter_class = AdapterRegistry.get_for_url("https://unknown-site.com/book/123")
        assert adapter_class is None
    
    def test_get_adapter_function(self):
        adapter = get_adapter("https://guji.nlc.cn/book/123")
        assert adapter is not None
        assert isinstance(adapter, BaseSiteAdapter)


class TestNLCGujiAdapter:
    """Tests for NLC Guji adapter."""

    def test_extract_book_id_metadata_param(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter

        adapter = NLCGujiAdapter()
        book_id = adapter.extract_book_id(
            "https://guji.nlc.cn/guji/pjkf/detail?metadataId=0021001379780000"
        )
        assert book_id == "0021001379780000"

    def test_extract_book_id_simple(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter

        adapter = NLCGujiAdapter()
        book_id = adapter.extract_book_id(
            "https://guji.nlc.cn/resource/resourceDetail?id=1001254"
        )
        assert book_id == "1001254"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter
        from bookget.exceptions import MetadataExtractionError

        adapter = NLCGujiAdapter()
        with pytest.raises(MetadataExtractionError):
            adapter.extract_book_id("https://guji.nlc.cn/")

    def test_can_handle(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter

        assert NLCGujiAdapter.can_handle("https://guji.nlc.cn/guji/pjkf/detail?metadataId=1011141")
        assert NLCGujiAdapter.can_handle("https://GUJI.NLC.CN/resource/resourceDetail?id=123")
        assert not NLCGujiAdapter.can_handle("https://ctext.org/analects")

    def test_parse_metadata(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter

        adapter = NLCGujiAdapter()
        data = {
            "parallelTitle": [{
                "title": "周易：九卷，略例：一卷",
                "creators": [
                    {"creator": "王弼", "role": "注", "statementOfResponsiblePerson": "三國魏"},
                    {"creator": "韓康伯", "role": "注", "statementOfResponsiblePerson": "晉"},
                ]
            }],
            "publisher": {
                "publishing": [{
                    "publisher": "",
                    "placeOfPublication": "",
                    "issuedGregorian": {
                        "issuedChineseCalendar": "宋",
                        "issuedGregorianCalendar": "960-1279"
                    }
                }]
            },
            "physicalDescription": [{"quantity": "3冊", "binding": "綫裝", "dimension": ["15.9×24.3cm"]}],
            "description": [{"paragraphFormat": ["12行21～22字"]}],
            "subject": [{"fdc": ["經部　易類　傳說之屬"]}],
            "location": [{"collectionUnit": "國家圖書館", "callNumber": ["03337"]}],
            "type": "漢文古籍",
            "language": "漢語",
            "provenance": [{"inscriptionWriter": [
                {"inscriptionWriter": "文嘉", "writerStat": "明", "inscriptionRole": "題款"}
            ]}],
        }

        metadata = adapter._parse_metadata(data, "1011141")

        assert metadata.title == "周易：九卷，略例：一卷"
        assert len(metadata.creators) == 2
        assert metadata.creators[0].name == "王弼"
        assert metadata.creators[0].role == "注"
        assert metadata.creators[0].dynasty == "三國魏"
        assert metadata.dynasty == "宋"
        assert metadata.date_normalized == "960-1279"
        assert metadata.volume_info == "3冊"
        assert metadata.binding == "綫裝"
        assert metadata.dimensions == "15.9×24.3cm"
        assert metadata.layout == "12行21～22字"
        assert metadata.category == "經部　易類　傳說之屬"
        assert metadata.collection_unit == "國家圖書館"
        assert metadata.call_number == "03337"
        assert metadata.doc_type == "漢文古籍"
        assert metadata.language == "漢語"
        assert len(metadata.provenance) == 1
        assert "文嘉" in metadata.provenance[0]

    def test_parse_metadata_empty(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter

        adapter = NLCGujiAdapter()
        metadata = adapter._parse_metadata({}, "test_id")

        assert metadata.title == ""
        assert metadata.creators == []
        assert metadata.source_id == "test_id"

    def test_make_source(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter

        adapter = NLCGujiAdapter()
        source = adapter._make_source("1011141")

        assert source["site"] == "nlc_guji"
        assert "1011141" in source["url"]
        assert source["book_id"] == "1011141"
        assert "downloaded_at" in source

    def test_strip_html_tags(self):
        from bookget.adapters.chinese.nlc_guji import NLCGujiAdapter

        # Normal HTML with spans
        html = '<p><span class="chars">時</span><span class="chars">而</span><span class="punctuation" data-comma="，">，</span></p>'
        assert NLCGujiAdapter._strip_html_tags(html) == "時而，"

        # Blank page marker
        html = '<p><span class="blank">[=此叶为空白叶页=]</span></p>'
        assert NLCGujiAdapter._strip_html_tags(html) is None

        # Empty content
        assert NLCGujiAdapter._strip_html_tags("<p></p>") is None
        assert NLCGujiAdapter._strip_html_tags("") is None


class TestNDLAdapter:
    """Tests for NDL adapter."""
    
    def test_extract_book_id(self):
        from bookget.adapters.iiif.ndl import NDLAdapter
        
        adapter = NDLAdapter()
        book_id = adapter.extract_book_id("https://dl.ndl.go.jp/pid/2592420")
        assert book_id == "2592420"
    
    def test_extract_book_id_with_page(self):
        from bookget.adapters.iiif.ndl import NDLAdapter
        
        adapter = NDLAdapter()
        book_id = adapter.extract_book_id("https://dl.ndl.go.jp/pid/2592420/1/5")
        assert book_id == "2592420"
    
    def test_manifest_url(self):
        from bookget.adapters.iiif.ndl import NDLAdapter
        
        adapter = NDLAdapter()
        url = adapter.get_manifest_url("2592420")
        assert url == "https://dl.ndl.go.jp/api/iiif/2592420/manifest.json"


class TestHarvardAdapter:
    """Tests for Harvard adapter."""
    
    def test_extract_book_id(self):
        from bookget.adapters.iiif.harvard import HarvardAdapter
        
        adapter = HarvardAdapter()
        book_id = adapter.extract_book_id(
            "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990080724750203941"
        )
        assert book_id == "49-990080724750203941"


class TestCTextAdapter:
    """Tests for CText adapter."""

    def test_extract_book_id_path(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        book_id = adapter.extract_book_id("https://ctext.org/analects/xue-er")
        assert book_id == "path:analects/xue-er"

    def test_extract_book_id_path_with_lang(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        book_id = adapter.extract_book_id("https://ctext.org/analects/xue-er/zh")
        assert book_id == "path:analects/xue-er"

    def test_extract_book_id_node(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        book_id = adapter.extract_book_id("https://ctext.org/text.pl?node=12345")
        assert book_id == "node:12345"

    def test_extract_book_id_library(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        book_id = adapter.extract_book_id("https://ctext.org/library.pl?if=zh&file=147636&page=1")
        assert book_id == "library:147636"

    def test_extract_book_id_wiki_book(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        book_id = adapter.extract_book_id(
            "https://ctext.org/wiki.pl?if=gb&res=1347940")
        assert book_id == "wiki-book:1347940"

    def test_extract_book_id_wiki_chapter(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        book_id = adapter.extract_book_id(
            "https://ctext.org/wiki.pl?if=gb&chapter=3658735")
        assert book_id == "wiki-chapter:3658735"

    @pytest.mark.asyncio
    async def test_get_text_content(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        try:
            # Test with a well-known text
            book_id = "path:analects/xue-er"
            text = await adapter.get_text_content(book_id)

            assert text is not None
            assert len(text) > 0
            # Should contain classical Chinese characters
            assert "子曰" in text or "學而" in text
        finally:
            await adapter.close()

    @pytest.mark.asyncio
    async def test_get_metadata(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        try:
            book_id = "path:analects/xue-er"
            metadata = await adapter.get_metadata(book_id)

            assert metadata is not None
            assert metadata.title != ""
            assert metadata.language == "lzh"  # Classical Chinese
        finally:
            await adapter.close()

    @pytest.mark.asyncio
    async def test_get_library_images(self):
        from bookget.adapters.chinese.ctext import CTextAdapter

        adapter = CTextAdapter()
        try:
            # Test library image extraction
            book_id = "library:147636"
            images = await adapter.get_image_list(book_id)

            # Should find images
            assert len(images) > 0

            # Check first image structure
            first_img = images[0]
            assert first_img.url.startswith("https://library.ctext.org/")
            assert first_img.url.endswith(".jpg")
            assert first_img.order == 1
            assert first_img.page == "1"
        finally:
            await adapter.close()


class TestWikisourceAdapter:
    """Tests for Wikisource adapter."""

    def test_extract_book_id_wiki_path(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        adapter = WikisourceAdapter()
        book_id = adapter.extract_book_id("https://zh.wikisource.org/wiki/論語")
        assert book_id == "論語"

    def test_extract_book_id_chapter_path(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        adapter = WikisourceAdapter()
        book_id = adapter.extract_book_id(
            "https://zh.wikisource.org/wiki/論語/學而第一"
        )
        assert book_id == "論語/學而第一"

    def test_extract_book_id_zh_hant(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        adapter = WikisourceAdapter()
        book_id = adapter.extract_book_id(
            "https://zh.wikisource.org/zh-hant/論語"
        )
        assert book_id == "論語"

    def test_extract_book_id_encoded(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        adapter = WikisourceAdapter()
        book_id = adapter.extract_book_id(
            "https://zh.wikisource.org/wiki/%E8%AB%96%E8%AA%9E"
        )
        assert book_id == "論語"

    def test_extract_book_id_trailing_slash(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        adapter = WikisourceAdapter()
        book_id = adapter.extract_book_id("https://zh.wikisource.org/wiki/論語/")
        assert book_id == "論語"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter
        from bookget.exceptions import MetadataExtractionError

        adapter = WikisourceAdapter()
        with pytest.raises(MetadataExtractionError):
            adapter.extract_book_id("https://zh.wikisource.org/")

    def test_can_handle(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        assert WikisourceAdapter.can_handle("https://zh.wikisource.org/wiki/論語")
        assert not WikisourceAdapter.can_handle("https://en.wikisource.org/wiki/Test")
        assert not WikisourceAdapter.can_handle("https://ctext.org/analects")

    def test_parse_metadata(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        adapter = WikisourceAdapter()
        data = {
            "title": "論語/學而第一",
            "categories": [{"*": "論語"}, {"*": "儒家經典"}],
            "wikitext": {"*": "{{header2|author=[[作者:孔子|孔子]]}}"},
        }
        metadata = adapter._parse_metadata(data, "論語/學而第一")
        assert metadata.title == "論語"
        assert "論語" in metadata.subjects
        assert metadata.language == "lzh"
        assert len(metadata.creators) == 1
        assert metadata.creators[0].name == "孔子"

    def test_parse_metadata_no_author(self):
        from bookget.adapters.other.wikisource import WikisourceAdapter

        adapter = WikisourceAdapter()
        data = {"title": "詩經", "categories": [], "wikitext": {"*": ""}}
        metadata = adapter._parse_metadata(data, "詩經")
        assert metadata.title == "詩經"
        assert metadata.creators == []


class TestStanfordAdapter:
    """Tests for Stanford adapter."""

    def test_extract_book_id_druid(self):
        from bookget.adapters.iiif.stanford import StanfordAdapter

        adapter = StanfordAdapter()
        book_id = adapter.extract_book_id(
            "https://searchworks.stanford.edu/view/bb123cd4567"
        )
        assert book_id == "bb123cd4567"

    def test_extract_book_id_purl(self):
        from bookget.adapters.iiif.stanford import StanfordAdapter

        adapter = StanfordAdapter()
        book_id = adapter.extract_book_id(
            "https://purl.stanford.edu/wd297xz1362"
        )
        assert book_id == "wd297xz1362"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.iiif.stanford import StanfordAdapter

        adapter = StanfordAdapter()
        with pytest.raises(ValueError):
            adapter.extract_book_id("https://searchworks.stanford.edu/")

    def test_manifest_url(self):
        from bookget.adapters.iiif.stanford import StanfordAdapter

        adapter = StanfordAdapter()
        url = adapter.get_manifest_url("bb123cd4567")
        assert url == "https://purl.stanford.edu/bb123cd4567/iiif/manifest"

    def test_can_handle(self):
        from bookget.adapters.iiif.stanford import StanfordAdapter

        assert StanfordAdapter.can_handle("https://searchworks.stanford.edu/view/bb123cd4567")
        assert StanfordAdapter.can_handle("https://purl.stanford.edu/wd297xz1362")
        assert not StanfordAdapter.can_handle("https://ctext.org/analects")


class TestBerkeleyAdapter:
    """Tests for Berkeley adapter."""

    def test_extract_book_id(self):
        from bookget.adapters.iiif.stanford import BerkeleyAdapter

        adapter = BerkeleyAdapter()
        book_id = adapter.extract_book_id(
            "https://digicoll.lib.berkeley.edu/record/12345"
        )
        assert book_id == "12345"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.iiif.stanford import BerkeleyAdapter

        adapter = BerkeleyAdapter()
        with pytest.raises(ValueError):
            adapter.extract_book_id("https://digicoll.lib.berkeley.edu/")

    def test_manifest_url(self):
        from bookget.adapters.iiif.stanford import BerkeleyAdapter

        adapter = BerkeleyAdapter()
        url = adapter.get_manifest_url("12345")
        assert url == "https://digicoll.lib.berkeley.edu/iiif/12345/manifest.json"

    def test_can_handle(self):
        from bookget.adapters.iiif.stanford import BerkeleyAdapter

        assert BerkeleyAdapter.can_handle("https://digicoll.lib.berkeley.edu/record/123")
        assert not BerkeleyAdapter.can_handle("https://ctext.org/analects")


class TestPrincetonAdapter:
    """Tests for Princeton adapter."""

    def test_extract_book_id_catalog(self):
        from bookget.adapters.iiif.princeton import PrincetonAdapter

        adapter = PrincetonAdapter()
        book_id = adapter.extract_book_id(
            "https://dpul.princeton.edu/eastasian/catalog/abc-123-def"
        )
        assert book_id == "abc-123-def"

    def test_extract_book_id_figgy(self):
        from bookget.adapters.iiif.princeton import PrincetonAdapter

        adapter = PrincetonAdapter()
        book_id = adapter.extract_book_id(
            "https://figgy.princeton.edu/concern/scanned_resources/abc123/manifest"
        )
        assert book_id == "abc123"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.iiif.princeton import PrincetonAdapter

        adapter = PrincetonAdapter()
        with pytest.raises(ValueError):
            adapter.extract_book_id("https://dpul.princeton.edu/")

    def test_manifest_url(self):
        from bookget.adapters.iiif.princeton import PrincetonAdapter

        adapter = PrincetonAdapter()
        url = adapter.get_manifest_url("abc-123-def")
        assert url == "https://figgy.princeton.edu/concern/scanned_resources/abc-123-def/manifest"

    def test_can_handle(self):
        from bookget.adapters.iiif.princeton import PrincetonAdapter

        assert PrincetonAdapter.can_handle("https://dpul.princeton.edu/eastasian/catalog/abc")
        assert PrincetonAdapter.can_handle("https://figgy.princeton.edu/concern/scanned_resources/abc")
        assert not PrincetonAdapter.can_handle("https://ctext.org/analects")


class TestBnFGallicaAdapter:
    """Tests for BnF Gallica adapter."""

    def test_extract_book_id(self):
        from bookget.adapters.other.european import BnFGallicaAdapter

        adapter = BnFGallicaAdapter()
        book_id = adapter.extract_book_id(
            "https://gallica.bnf.fr/ark:/12148/btv1b9006423x"
        )
        assert book_id == "btv1b9006423x"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.other.european import BnFGallicaAdapter

        adapter = BnFGallicaAdapter()
        with pytest.raises(ValueError):
            adapter.extract_book_id("https://gallica.bnf.fr/")

    def test_manifest_url(self):
        from bookget.adapters.other.european import BnFGallicaAdapter

        adapter = BnFGallicaAdapter()
        url = adapter.get_manifest_url("btv1b9006423x")
        assert url == "https://gallica.bnf.fr/iiif/ark:/12148/btv1b9006423x/manifest.json"

    def test_can_handle(self):
        from bookget.adapters.other.european import BnFGallicaAdapter

        assert BnFGallicaAdapter.can_handle("https://gallica.bnf.fr/ark:/12148/btv1b9006423x")
        assert not BnFGallicaAdapter.can_handle("https://ctext.org/analects")


class TestBritishLibraryAdapter:
    """Tests for British Library adapter."""

    def test_extract_book_id_ref(self):
        from bookget.adapters.other.european import BritishLibraryAdapter

        adapter = BritishLibraryAdapter()
        book_id = adapter.extract_book_id(
            "https://www.bl.uk/manuscripts/Viewer.aspx?ref=or_8210_p2"
        )
        assert book_id == "or_8210_p2"

    def test_extract_book_id_items(self):
        from bookget.adapters.other.european import BritishLibraryAdapter

        adapter = BritishLibraryAdapter()
        book_id = adapter.extract_book_id(
            "https://www.bl.uk/items/diamond-sutra"
        )
        assert book_id == "diamond-sutra"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.other.european import BritishLibraryAdapter

        adapter = BritishLibraryAdapter()
        with pytest.raises(ValueError):
            adapter.extract_book_id("https://www.bl.uk/")

    def test_manifest_url(self):
        from bookget.adapters.other.european import BritishLibraryAdapter

        adapter = BritishLibraryAdapter()
        url = adapter.get_manifest_url("or_8210_p2")
        assert url == "https://api.bl.uk/metadata/iiif/or_8210_p2/manifest.json"

    def test_can_handle(self):
        from bookget.adapters.other.european import BritishLibraryAdapter

        assert BritishLibraryAdapter.can_handle("https://www.bl.uk/manuscripts/Viewer.aspx?ref=123")
        assert BritishLibraryAdapter.can_handle("https://bl.uk/collection-items/test")
        assert not BritishLibraryAdapter.can_handle("https://ctext.org/analects")


class TestBSBAdapter:
    """Tests for Bayerische Staatsbibliothek adapter."""

    def test_extract_book_id_bsb_pattern(self):
        from bookget.adapters.other.european import BayerischeStaatsbibliothekAdapter

        adapter = BayerischeStaatsbibliothekAdapter()
        book_id = adapter.extract_book_id(
            "https://www.digitale-sammlungen.de/de/view/bsb00023986"
        )
        assert book_id == "bsb00023986"

    def test_extract_book_id_view_pattern(self):
        from bookget.adapters.other.european import BayerischeStaatsbibliothekAdapter

        adapter = BayerischeStaatsbibliothekAdapter()
        book_id = adapter.extract_book_id(
            "https://www.digitale-sammlungen.de/de/view/some_other_id"
        )
        assert book_id == "some_other_id"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.other.european import BayerischeStaatsbibliothekAdapter

        adapter = BayerischeStaatsbibliothekAdapter()
        with pytest.raises(ValueError):
            adapter.extract_book_id("https://www.digitale-sammlungen.de/")

    def test_manifest_url(self):
        from bookget.adapters.other.european import BayerischeStaatsbibliothekAdapter

        adapter = BayerischeStaatsbibliothekAdapter()
        url = adapter.get_manifest_url("bsb00023986")
        assert url == "https://api.digitale-sammlungen.de/iiif/presentation/v2/bsb00023986/manifest"

    def test_can_handle(self):
        from bookget.adapters.other.european import BayerischeStaatsbibliothekAdapter

        assert BayerischeStaatsbibliothekAdapter.can_handle(
            "https://www.digitale-sammlungen.de/de/view/bsb00023986"
        )
        assert not BayerischeStaatsbibliothekAdapter.can_handle("https://ctext.org/analects")


class TestNCLTaiwanAdapter:
    """Tests for NCL Taiwan adapter."""

    def test_extract_book_id_path(self):
        from bookget.adapters.other.taiwan import NCLTaiwanAdapter

        adapter = NCLTaiwanAdapter()
        book_id = adapter.extract_book_id(
            "https://rbook.ncl.edu.tw/ncltwcatchtitle/123456"
        )
        assert book_id == "123456"

    def test_extract_book_id_query_param(self):
        from bookget.adapters.other.taiwan import NCLTaiwanAdapter

        adapter = NCLTaiwanAdapter()
        book_id = adapter.extract_book_id(
            "https://rbook2.ncl.edu.tw/viewer?id=789"
        )
        assert book_id == "789"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.other.taiwan import NCLTaiwanAdapter

        adapter = NCLTaiwanAdapter()
        with pytest.raises(ValueError):
            adapter.extract_book_id("https://rbook.ncl.edu.tw/")

    def test_manifest_url(self):
        from bookget.adapters.other.taiwan import NCLTaiwanAdapter

        adapter = NCLTaiwanAdapter()
        url = adapter.get_manifest_url("123456")
        assert url == "https://rbook.ncl.edu.tw/iiif/ncltwcatchtitle/123456/manifest"

    def test_can_handle(self):
        from bookget.adapters.other.taiwan import NCLTaiwanAdapter

        assert NCLTaiwanAdapter.can_handle("https://rbook.ncl.edu.tw/ncltwcatchtitle/123")
        assert NCLTaiwanAdapter.can_handle("https://rbook2.ncl.edu.tw/viewer?id=456")
        assert not NCLTaiwanAdapter.can_handle("https://ctext.org/analects")


class TestPalaceMuseumTaipeiAdapter:
    """Tests for Palace Museum Taipei adapter."""

    def test_extract_book_id(self):
        from bookget.adapters.other.taiwan import PalaceMuseumTaipeiAdapter

        adapter = PalaceMuseumTaipeiAdapter()
        book_id = adapter.extract_book_id(
            "https://digitalarchive.npm.gov.tw/Painting/Content?pid=12345"
        )
        assert book_id == "12345"

    def test_extract_book_id_multiple_params(self):
        from bookget.adapters.other.taiwan import PalaceMuseumTaipeiAdapter

        adapter = PalaceMuseumTaipeiAdapter()
        book_id = adapter.extract_book_id(
            "https://digitalarchive.npm.gov.tw/Painting/Content?type=1&pid=67890"
        )
        assert book_id == "67890"

    def test_extract_book_id_invalid(self):
        from bookget.adapters.other.taiwan import PalaceMuseumTaipeiAdapter
        from bookget.exceptions import MetadataExtractionError

        adapter = PalaceMuseumTaipeiAdapter()
        with pytest.raises(MetadataExtractionError):
            adapter.extract_book_id("https://digitalarchive.npm.gov.tw/")

    def test_can_handle(self):
        from bookget.adapters.other.taiwan import PalaceMuseumTaipeiAdapter

        assert PalaceMuseumTaipeiAdapter.can_handle(
            "https://digitalarchive.npm.gov.tw/Painting/Content?pid=123"
        )
        assert not PalaceMuseumTaipeiAdapter.can_handle("https://ctext.org/analects")


class TestAdapterRegistryComprehensive:
    """Additional registry tests for newly-tested adapters."""

    def test_get_for_url_wikisource(self):
        adapter_class = AdapterRegistry.get_for_url("https://zh.wikisource.org/wiki/論語")
        assert adapter_class is not None
        assert adapter_class.site_id == "wikisource"

    def test_get_for_url_stanford(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://searchworks.stanford.edu/view/bb123cd4567"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "stanford"

    def test_get_for_url_berkeley(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://digicoll.lib.berkeley.edu/record/12345"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "berkeley"

    def test_get_for_url_princeton(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://dpul.princeton.edu/eastasian/catalog/abc-123"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "princeton"

    def test_get_for_url_british_library(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://www.bl.uk/manuscripts/Viewer.aspx?ref=or_8210"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "british_library"

    def test_get_for_url_bsb(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://www.digitale-sammlungen.de/de/view/bsb00023986"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "bsb"

    def test_get_for_url_ncl_taiwan(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://rbook.ncl.edu.tw/ncltwcatchtitle/123"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "ncl_taiwan"

    def test_get_for_url_npm_taipei(self):
        adapter_class = AdapterRegistry.get_for_url(
            "https://digitalarchive.npm.gov.tw/Painting/Content?pid=123"
        )
        assert adapter_class is not None
        assert adapter_class.site_id == "npm_taipei"
