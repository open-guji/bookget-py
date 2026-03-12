# Tests for Hanchi (漢籍全文資料庫) adapter and parser

import pytest
from bookget.adapters.other.hanchi import HanchiAdapter, _SLUG_TO_CGI, _CGI_CONFIGS
from bookget.text_parsers.hanchi_parser import HanchiParser
from bookget.text_parsers.base import StructuredText
from bookget.exceptions import MetadataExtractionError


# =====================================================================
# HanchiAdapter — URL parsing
# =====================================================================

class TestHanchiAdapterURLParsing:
    """Tests for extract_book_id and related URL helpers."""

    def setup_method(self):
        self.adapter = HanchiAdapter()

    def test_extract_book_id_book_level(self):
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^1440492097^802^^^30211001@@341159809"
        assert self.adapter.extract_book_id(url) == "hanjishilu:30211001"

    def test_extract_book_id_chapter_level(self):
        """Chapter-level URLs should map back to book node."""
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^1440492097^802^^^60211001000500050002@@1795010443"
        assert self.adapter.extract_book_id(url) == "hanjishilu:30211001"

    def test_extract_book_id_volume_group_level(self):
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^123^802^^^402110010005@@999"
        assert self.adapter.extract_book_id(url) == "hanjishilu:30211001"

    def test_extract_book_id_volume_level(self):
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^123^802^^^5021100100050005@@999"
        assert self.adapter.extract_book_id(url) == "hanjishilu:30211001"

    def test_extract_book_id_with_extra_suffix(self):
        """URLs with extra ^N suffix (friendly print)."""
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^123^810^^^60211001000500050002^N@@999"
        assert self.adapter.extract_book_id(url) == "hanjishilu:30211001"

    def test_extract_book_id_with_fragment(self):
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^123^802^^^30211001@@999#top"
        assert self.adapter.extract_book_id(url) == "hanjishilu:30211001"

    def test_extract_book_id_hanjiquery(self):
        url = "https://hanchi.ihp.sinica.edu.tw/ihpc/hanjiquery?@1^123^802^^^30001001@@999"
        assert self.adapter.extract_book_id(url) == "hanjiquery:30001001"

    def test_extract_book_id_ttsweb(self):
        url = "https://hanchi.ihp.sinica.edu.tw/ihpc/ttsweb?@1^123^802^^^30002001@@999"
        assert self.adapter.extract_book_id(url) == "ttsweb:30002001"

    def test_extract_book_id_spawn_url_raises(self):
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?1:1440492097:10:/raid/ihp_ebook2/hanji/ttsweb.ini:::@SPAWN"
        with pytest.raises(MetadataExtractionError, match="SPAWN"):
            self.adapter.extract_book_id(url)

    def test_extract_book_id_no_node_raises(self):
        url = "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?somegarbage"
        with pytest.raises(MetadataExtractionError, match="Could not extract"):
            self.adapter.extract_book_id(url)

    def test_extract_book_id_unknown_cgi_raises(self):
        url = "https://hanchi.ihp.sinica.edu.tw/unknown/program?@1^123^802^^^30001001@@999"
        with pytest.raises(MetadataExtractionError, match="Unknown Hanchi CGI"):
            self.adapter.extract_book_id(url)


class TestNodeToBookNode:
    """Tests for _node_to_book_node static method."""

    def test_book_node_unchanged(self):
        assert HanchiAdapter._node_to_book_node("30211001") == "30211001"

    def test_volume_group_to_book(self):
        assert HanchiAdapter._node_to_book_node("402110010005") == "30211001"

    def test_volume_to_book(self):
        assert HanchiAdapter._node_to_book_node("5021100100050005") == "30211001"

    def test_chapter_to_book(self):
        assert HanchiAdapter._node_to_book_node("60211001000500050002") == "30211001"

    def test_deep_node_to_book(self):
        """Prefix 7 and 8 nodes should also map back correctly."""
        assert HanchiAdapter._node_to_book_node("702110010005000500030002") == "30211001"
        assert HanchiAdapter._node_to_book_node("8021100100050005000300010001") == "30211001"

    def test_different_book(self):
        # 清實錄 has a different book code
        assert HanchiAdapter._node_to_book_node("30211003") == "30211003"
        assert HanchiAdapter._node_to_book_node("402110030001") == "30211003"


class TestParseBookId:
    """Tests for _parse_book_id."""

    def setup_method(self):
        self.adapter = HanchiAdapter()

    def test_valid_split(self):
        slug, node = self.adapter._parse_book_id("hanjishilu:30211001")
        assert slug == "hanjishilu"
        assert node == "30211001"

    def test_no_colon_raises(self):
        with pytest.raises(MetadataExtractionError, match="Invalid"):
            self.adapter._parse_book_id("invalid_format")


class TestSlugToCgiPath:
    """Tests for _slug_to_cgi_path."""

    def test_known_slugs(self):
        assert HanchiAdapter._slug_to_cgi_path("hanjishilu") == "/mqlc/hanjishilu"
        assert HanchiAdapter._slug_to_cgi_path("hanjiquery") == "/ihpc/hanjiquery"
        assert HanchiAdapter._slug_to_cgi_path("ttsweb") == "/ihpc/ttsweb"

    def test_unknown_slug_raises(self):
        with pytest.raises(MetadataExtractionError, match="Unknown"):
            HanchiAdapter._slug_to_cgi_path("nonexistent")


class TestCanHandle:
    """Tests for adapter domain matching."""

    def test_hanchi_url(self):
        assert HanchiAdapter.can_handle(
            "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^123^802^^^30211001@@999"
        )

    def test_hanchi_url_case_insensitive(self):
        assert HanchiAdapter.can_handle(
            "https://HANCHI.IHP.SINICA.EDU.TW/mqlc/hanjishilu?@1^123^802^^^30211001@@999"
        )

    def test_non_hanchi_url(self):
        assert not HanchiAdapter.can_handle("https://ctext.org/analects")
        assert not HanchiAdapter.can_handle("https://guji.nlc.cn/book/123")


class TestAdapterRegistration:
    """Tests for adapter registry integration."""

    def test_registry_finds_hanchi(self):
        from bookget.adapters.registry import AdapterRegistry

        cls = AdapterRegistry.get_for_url(
            "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu?@1^123^802^^^30211001@@999"
        )
        assert cls is not None
        assert cls.site_id == "hanchi"

    def test_adapter_properties(self):
        adapter = HanchiAdapter()
        assert adapter.site_id == "hanchi"
        assert adapter.supports_text is True
        assert adapter.supports_images is False
        assert adapter.supports_iiif is False
        assert adapter.supports_pdf is False


# =====================================================================
# HanchiAdapter — URL building
# =====================================================================

class TestBuildUrl:
    """Tests for _build_url."""

    def setup_method(self):
        self.adapter = HanchiAdapter()
        from bookget.adapters.other.hanchi import HanchiSession
        self.hs = HanchiSession(
            session_id="12345", cgi_path="/mqlc/hanjishilu",
            flag="1", checksum="99999",
        )

    def test_basic_url(self):
        url = self.adapter._build_url(self.hs, 802, "30211001")
        assert url == (
            "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu"
            "?@1^12345^802^^^30211001@@99999"
        )

    def test_url_with_extra(self):
        url = self.adapter._build_url(self.hs, 810, "60211001000500050002", extra="N")
        assert url == (
            "https://hanchi.ihp.sinica.edu.tw/mqlc/hanjishilu"
            "?@1^12345^810^^^60211001000500050002^N@@99999"
        )

    def test_url_without_node(self):
        url = self.adapter._build_url(self.hs, 10)
        assert "^^^@@99999" in url


# =====================================================================
# HanchiAdapter — HTML parsing (static methods)
# =====================================================================

class TestParseContentPage:
    """Tests for _parse_content_page static method."""

    @staticmethod
    def _get_all_paragraphs(result):
        """Helper: collect all paragraphs from pages-based result."""
        paras = []
        for page in result.get("pages", []):
            paras.extend(page.get("paragraphs", []))
        return paras

    def test_basic_extraction(self):
        html = '''
        <a href="foo" class=gobookmark title="test">史／編年／明實錄／太祖／卷一(P.4)</a>
        <SPAN id=fontstyle style="FONT-SIZE: 12pt;">
        <div style="text-indent:0em;">辛卯夏五月汝潁兵起</div>
        <div style="text-indent:0em;">壬辰春二月乙亥朔</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert result is not None
        assert result["title"] == "卷一"
        assert result["breadcrumb"] == "史／編年／明實錄／太祖／卷一(P.4)"
        assert self._get_all_paragraphs(result) == ["辛卯夏五月汝潁兵起", "壬辰春二月乙亥朔"]

    def test_strips_collation_notes(self):
        html = '''
        <a class=gobookmark>史／明實錄／太祖(P.1)</a>
        <SPAN id=fontstyle>
        <div>正文開始</div>
        <span id=q00><b>校勘記:某某異文</b></span>
        <div>正文繼續</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert result is not None
        paras = self._get_all_paragraphs(result)
        assert len(paras) == 2
        assert "校勘記" not in " ".join(paras)

    def test_collation_note_converted_to_bracket(self):
        """Collation notes in <span id=q...> are converted to 【…】."""
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <div>文字<a onclick="q01" href="#">x</a><span id=q01>原文:廣本作某</span>繼續</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        paras = self._get_all_paragraphs(result)
        assert len(paras) == 1
        assert "【原文:廣本作某】" in paras[0]

    def test_editorial_gif_markers(self):
        """Editorial GIF icons (贅/補) are converted to inline text markers."""
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <div>振武衛指揮同知尋<img src=/mql/hanjishiluimg/qd.gif>還<img src=/mql/hanjishiluimg/qa.gif>遷鷹揚衛</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        paras = self._get_all_paragraphs(result)
        assert len(paras) == 1
        assert "尋(贅)還(補)遷" in paras[0]

    def test_unknown_gif_raises_error(self):
        """Unknown editorial GIF icons should raise AdapterError."""
        from bookget.exceptions import AdapterError
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <div>文字<img src=/mql/hanjishiluimg/qz.gif>繼續</div>
        </SPAN>
        '''
        with pytest.raises(AdapterError, match="未知的 Hanchi 校勘图标"):
            HanchiAdapter._parse_content_page(html)

    def test_unknown_span_content_raises_error(self):
        """Span with unknown content format should raise AdapterError."""
        from bookget.exceptions import AdapterError
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <div>文字<span id=q99>未知格式無冒號</span>繼續</div>
        </SPAN>
        '''
        with pytest.raises(AdapterError, match="未知的 Hanchi 校勘 span"):
            HanchiAdapter._parse_content_page(html)

    def test_unknown_img_raises_error(self):
        """Any remaining <img> tag after processing should raise AdapterError."""
        from bookget.exceptions import AdapterError
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <div>文字<img src="unknown.jpg">繼續</div>
        </SPAN>
        '''
        with pytest.raises(AdapterError, match="未处理的 <img> 标签"):
            HanchiAdapter._parse_content_page(html)

    def test_strips_page_tables(self):
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <table class=page><tr><td class=page><a name=P0></a>...4...</table>
        <div>第一段</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert result is not None
        assert self._get_all_paragraphs(result) == ["第一段"]

    def test_strips_viewpdf_links(self):
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <a class=viewpdf href="some_pdf">圖</a>
        <div>段落文字</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert self._get_all_paragraphs(result) == ["段落文字"]

    def test_extracts_h3_headings(self):
        html = '''
        <a class=gobookmark>明實錄(P.1)</a>
        <SPAN id=fontstyle>
        <h3><b>太祖高皇帝實錄序</b></h3>
        <div>序文內容</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert self._get_all_paragraphs(result) == ["太祖高皇帝實錄序", "序文內容"]

    def test_strips_inline_html_from_paragraphs(self):
        html = '''
        <a class=gobookmark>測試(P.1)</a>
        <SPAN id=fontstyle>
        <div>文字<b>加粗</b>繼續<a href="foo">鏈接</a>結束</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert self._get_all_paragraphs(result) == ["文字加粗繼續鏈接結束"]

    def test_skips_empty_paragraphs(self):
        html = '''
        <a class=gobookmark>測試(P.1)</a>
        <SPAN id=fontstyle>
        <div>有內容</div>
        <div>   </div>
        <div></div>
        <div>也有內容</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert self._get_all_paragraphs(result) == ["有內容", "也有內容"]

    def test_returns_none_when_no_fontstyle(self):
        html = '<html><body>No fontstyle span here</body></html>'
        assert HanchiAdapter._parse_content_page(html) is None

    def test_returns_none_when_no_paragraphs(self):
        html = '''
        <a class=gobookmark>空頁(P.1)</a>
        <SPAN id=fontstyle>
        <table class=page><tr><td>...1...</td></tr></table>
        </SPAN>
        '''
        assert HanchiAdapter._parse_content_page(html) is None

    def test_page_marker_stripped_from_title(self):
        html = '''
        <a class=gobookmark>史／明實錄／太祖(P.123)</a>
        <SPAN id=fontstyle>
        <div>內容</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert result["title"] == "太祖"

    def test_garbled_page_marker_stripped(self):
        """Encoding-damaged page markers like (P.Æ=^Æ) should be stripped."""
        html = '''
        <a class=gobookmark>史／版本說明(P.\ufffd=^\ufffd)</a>
        <SPAN id=fontstyle>
        <div>內容</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_content_page(html)
        assert result["title"] == "版本說明"


class TestParseFriendlyPrint:
    """Tests for _parse_friendly_print static method."""

    def test_basic_extraction(self):
        html = '''
        <font style="font-size:12pt;color:#0066CC;font-weight:bold;">
          史／編年／明實錄／太祖／卷一　辛卯歲至甲午歲／辛卯歲五月(P.4)
        </font>
        <SPAN id=fontstyle>
        <div>辛卯夏五月汝潁兵起</div>
        <div>壬辰春二月乙亥朔</div>
        </SPAN>
        '''
        result = HanchiAdapter._parse_friendly_print(html)
        assert result is not None
        assert result["title"] == "辛卯歲五月"
        paras = []
        for page in result.get("pages", []):
            paras.extend(page.get("paragraphs", []))
        assert len(paras) == 2

    def test_returns_none_without_fontstyle(self):
        html = '<font style="color:#0066CC">標題</font><p>沒有fontstyle</p>'
        assert HanchiAdapter._parse_friendly_print(html) is None


class TestParseBookMetadata:
    """Tests for _parse_book_metadata static method."""

    def test_full_metadata(self):
        html = '''
        <a href="foo" class=gobookmark title="test">史／編年／明實錄</a>
        <img src=/mql/hanjishiluimg/imgbook2.gif border=0 align=absmiddle
             title='臺北市 : 中央研究院歷史語言研究所, 民55[1966]，中央研究院歷史語言研究所校勘'>
        '''
        meta = HanchiAdapter._parse_book_metadata(html, "hanjishilu:30211001")
        assert meta.title == "明實錄"
        assert meta.category == "史／編年／明實錄"
        assert meta.place == "臺北市"
        assert meta.publisher == "中央研究院歷史語言研究所"
        assert meta.date == "民55[1966]"
        assert meta.language == "lzh"
        assert meta.collection_unit == "中央研究院歷史語言研究所"
        assert len(meta.notes) == 1
        assert "校勘" in meta.notes[0]

    def test_metadata_without_publisher(self):
        html = '''
        <a class=gobookmark>經／周易</a>
        '''
        meta = HanchiAdapter._parse_book_metadata(html, "hanjiquery:30001001")
        assert meta.title == "周易"
        assert meta.category == "經／周易"
        assert meta.publisher == ""
        assert meta.language == "lzh"

    def test_metadata_no_breadcrumb(self):
        html = '<html><body>Nothing here</body></html>'
        meta = HanchiAdapter._parse_book_metadata(html, "test:30001001")
        assert meta.title == ""
        assert meta.source_id == "test:30001001"
        assert meta.language == "lzh"

    def test_metadata_source_id(self):
        html = '<a class=gobookmark>史／明實錄</a>'
        meta = HanchiAdapter._parse_book_metadata(html, "hanjishilu:30211001")
        assert meta.source_id == "hanjishilu:30211001"


class TestUpdateChecksum:
    """Tests for _update_checksum."""

    def setup_method(self):
        self.adapter = HanchiAdapter()

    def test_updates_to_last_checksum(self):
        from bookget.adapters.other.hanchi import HanchiSession
        hs = HanchiSession(
            session_id="123", cgi_path="/mqlc/hanjishilu",
            flag="1", checksum="111",
        )
        html = '''
        hanjishilu?@1^123^802^^^30211001@@222
        hanjishilu?@1^123^801^^^30211001^太祖@@333
        hanjishilu?@1^123^805^^^30211001@@444
        '''
        self.adapter._update_checksum(hs, html)
        assert hs.checksum == "444"

    def test_no_update_if_no_links(self):
        from bookget.adapters.other.hanchi import HanchiSession
        hs = HanchiSession(
            session_id="123", cgi_path="/mqlc/hanjishilu",
            flag="1", checksum="original",
        )
        self.adapter._update_checksum(hs, "<html>no links</html>")
        assert hs.checksum == "original"


# =====================================================================
# HanchiAdapter — CGI configuration
# =====================================================================

class TestCGIConfig:
    """Tests for CGI config dictionaries."""

    def test_slug_to_cgi_completeness(self):
        """Every CGI config should have a reverse slug entry."""
        for path in _CGI_CONFIGS:
            slug = path.rsplit("/", 1)[-1]
            assert slug in _SLUG_TO_CGI
            assert _SLUG_TO_CGI[slug] == path

    def test_known_configs(self):
        assert "/mqlc/hanjishilu" in _CGI_CONFIGS
        assert "/ihpc/hanjiquery" in _CGI_CONFIGS
        assert "/ihpc/ttsweb" in _CGI_CONFIGS

    def test_configs_have_required_keys(self):
        for path, cfg in _CGI_CONFIGS.items():
            assert "ttsweb_path" in cfg, f"{path} missing ttsweb_path"
            assert "ini_name" in cfg, f"{path} missing ini_name"


# =====================================================================
# HanchiParser
# =====================================================================

class TestHanchiParser:
    """Tests for HanchiParser text parser."""

    def setup_method(self):
        self.parser = HanchiParser()

    def test_parse_book_multi_chapter(self):
        chapters = [
            {
                "node_id": "60211001000500050002",
                "title": "辛卯歲五月",
                "breadcrumb": "史／明實錄／太祖",
                "paragraphs": ["辛卯夏五月汝潁兵起", "壬辰春二月"],
            },
            {
                "node_id": "60211001000500050003",
                "title": "壬辰歲二月",
                "breadcrumb": "史／明實錄／太祖",
                "paragraphs": ["壬辰春二月乙亥朔日有食之"],
            },
        ]
        meta = {"title": "明實錄", "category": "史／編年", "publisher": "中研院"}
        st = self.parser.parse_book(
            chapters, meta, "hanjishilu:30211001", "https://example.com"
        )

        assert st.title == "明實錄"
        assert st.content_type == "book_with_chapters"
        assert len(st.chapters) == 2
        assert st.chapters[0]["id"] == "60211001000500050002"
        assert st.chapters[0]["title"] == "辛卯歲五月"
        assert st.chapters[0]["order"] == 1
        assert st.chapters[0]["breadcrumb"] == "史／明實錄／太祖"
        assert st.chapters[0]["paragraphs"] == ["辛卯夏五月汝潁兵起", "壬辰春二月"]
        assert st.chapters[1]["order"] == 2

    def test_parse_book_single_chapter(self):
        chapters = [
            {
                "node_id": "50211001",
                "title": "版本說明",
                "paragraphs": ["說明文字"],
            },
        ]
        meta = {"title": "明實錄"}
        st = self.parser.parse_book(
            chapters, meta, "hanjishilu:30211001", "https://example.com"
        )
        assert st.content_type == "single_chapter"
        assert len(st.chapters) == 1

    def test_parse_book_empty_chapters(self):
        st = self.parser.parse_book(
            [], {"title": "空書"}, "test:30001001", "https://example.com"
        )
        assert len(st.chapters) == 0
        assert st.title == "空書"

    def test_parse_book_skips_empty_paragraphs(self):
        chapters = [
            {"node_id": "1", "title": "有內容", "paragraphs": ["文字"]},
            {"node_id": "2", "title": "無內容", "paragraphs": []},
            {"node_id": "3", "title": "也有", "paragraphs": ["更多文字"]},
        ]
        st = self.parser.parse_book(
            chapters, {"title": "測試"}, "test:30001001", "https://example.com"
        )
        assert len(st.chapters) == 2
        assert st.chapters[0]["title"] == "有內容"
        assert st.chapters[1]["title"] == "也有"

    def test_source_fields(self):
        chapters = [{"node_id": "1", "title": "Ch1", "paragraphs": ["text"]}]
        st = self.parser.parse_book(
            chapters, {"title": "Test"}, "hanjishilu:30211001",
            "https://example.com", index_id="idx001"
        )
        assert st.source["site"] == "hanchi"
        assert st.source["book_id"] == "hanjishilu:30211001"
        assert st.source["url"] == "https://example.com"
        assert st.source["index_id"] == "idx001"
        assert "downloaded_at" in st.source

    def test_metadata_fields(self):
        meta = {
            "title": "明實錄",
            "category": "史／編年",
            "publisher": "中研院",
            "place": "臺北市",
            "date": "民55[1966]",
            "notes": "校勘記",
        }
        chapters = [{"node_id": "1", "title": "Ch1", "paragraphs": ["text"]}]
        st = self.parser.parse_book(
            chapters, meta, "test:30001001", "https://example.com"
        )
        assert st.metadata["category"] == "史／編年"
        assert st.metadata["publisher"] == "中研院"
        assert st.metadata["place"] == "臺北市"
        assert st.metadata["date"] == "民55[1966]"
        assert st.metadata["collection"] == "中央研究院歷史語言研究所漢籍電子文獻"

    def test_metadata_empty_fields_skipped(self):
        meta = {"title": "Test", "category": "", "publisher": None}
        chapters = [{"node_id": "1", "title": "Ch1", "paragraphs": ["text"]}]
        st = self.parser.parse_book(
            chapters, meta, "test:30001001", "https://example.com"
        )
        assert "category" not in st.metadata
        assert "publisher" not in st.metadata
        assert "collection" in st.metadata  # always present

    def test_validate_output(self):
        chapters = [
            {"node_id": "1", "title": "Ch1", "paragraphs": ["text"]},
        ]
        st = self.parser.parse_book(
            chapters, {"title": "Valid"}, "test:30001001", "https://example.com"
        )
        errors = st.validate()
        assert errors == []

    def test_clean_paragraphs_strips_entities(self):
        result = self.parser._clean_paragraphs(["&amp;Hello&lt;World&gt;"])
        assert result == ["&Hello<World>"]

    def test_clean_paragraphs_removes_empty(self):
        result = self.parser._clean_paragraphs(["text", "", "  ", "more"])
        assert result == ["text", "more"]

    def test_clean_paragraphs_removes_decorative_separators(self):
        result = self.parser._clean_paragraphs([
            "．　．　．　．",
            "....",
            ". . . .",
            "正文",
        ])
        assert result == ["正文"]

    @pytest.mark.asyncio
    async def test_parse_async_interface(self):
        raw_data = {
            "chapters": [
                {"node_id": "1", "title": "Ch1", "paragraphs": ["text"]},
            ],
            "metadata": {"title": "Test"},
        }
        st = await self.parser.parse(
            raw_data, "test:30001001", "https://example.com"
        )
        assert st.title == "Test"
        assert len(st.chapters) == 1


# =====================================================================
# HanchiAdapter — live integration tests (require network)
# =====================================================================

@pytest.mark.asyncio
class TestHanchiLiveIntegration:
    """Live tests against the actual Hanchi server.

    These tests require network access. They are deliberately
    lightweight — one session spawn and one metadata fetch — to
    avoid putting excessive load on the public server.
    """

    async def test_spawn_session(self):
        adapter = HanchiAdapter()
        try:
            hs = await adapter._spawn_session("/mqlc/hanjishilu")
            assert hs.session_id
            assert hs.flag
            assert hs.checksum
            assert hs.cgi_path == "/mqlc/hanjishilu"
        finally:
            await adapter.close()

    async def test_get_metadata(self):
        adapter = HanchiAdapter()
        try:
            meta = await adapter.get_metadata("hanjishilu:30211001")
            assert meta.title == "明實錄"
            assert "史" in meta.category
            assert meta.language == "lzh"
            assert meta.publisher  # should be non-empty
        finally:
            await adapter.close()

    async def test_fetch_chapter_text(self):
        adapter = HanchiAdapter()
        try:
            hs = await adapter._spawn_session("/mqlc/hanjishilu")
            # Expand book node first (needed for tree context)
            await adapter._request(hs, action=801, node_id="30211001")
            # Fetch the 版本說明 leaf node
            text = await adapter._fetch_chapter_text(hs, "402110010001")
            assert text is not None
            assert len(text["pages"]) > 0
        finally:
            await adapter.close()
