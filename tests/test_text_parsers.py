"""Tests for text_parsers and text_converters modules."""

import json
import pytest
from ..text_parsers.base import StructuredText, BaseTextParser
from ..text_parsers.ctext_parser import CTextParser
from ..text_parsers.shidianguji_parser import ShidianGujiParser
from ..text_parsers.wikisource_parser import WikisourceParser
from ..text_converters.markdown_converter import MarkdownConverter
from ..text_converters.plaintext_converter import PlainTextConverter


# --- StructuredText ---

class TestStructuredText:
    def test_create_default(self):
        st = StructuredText()
        assert st.schema_version == "1.0"
        assert st.content_type == "single_chapter"
        assert st.chapters == []

    def test_to_dict(self):
        st = StructuredText(
            title="論語",
            content_type="single_chapter",
            chapters=[{"id": "1", "title": "學而", "order": 1, "paragraphs": ["子曰"]}],
        )
        d = st.to_dict()
        assert d["title"] == "論語"
        assert d["chapters"][0]["paragraphs"] == ["子曰"]

    def test_from_dict(self):
        data = {
            "schema_version": "1.0",
            "title": "詩經",
            "content_type": "book_with_chapters",
            "chapters": [
                {"id": "1", "title": "關雎", "order": 1, "paragraphs": ["關關雎鳩"]},
            ],
        }
        st = StructuredText.from_dict(data)
        assert st.title == "詩經"
        assert st.content_type == "book_with_chapters"
        assert len(st.chapters) == 1

    def test_roundtrip_json(self):
        st = StructuredText(
            title="Test",
            source={"site": "ctext", "url": "https://example.com"},
            chapters=[{"id": "1", "title": "Ch1", "order": 1, "paragraphs": ["hello"]}],
        )
        json_str = json.dumps(st.to_dict(), ensure_ascii=False)
        loaded = json.loads(json_str)
        st2 = StructuredText.from_dict(loaded)
        assert st2.title == st.title
        assert st2.chapters == st.chapters

    def test_validate_ok(self):
        st = StructuredText(
            title="OK",
            content_type="single_chapter",
            chapters=[{"id": "1", "title": "ch", "order": 1, "paragraphs": ["text"]}],
        )
        assert st.validate() == []

    def test_validate_errors(self):
        st = StructuredText(content_type="invalid_type")
        errors = st.validate()
        assert any("content_type" in e for e in errors)
        assert any("title" in e for e in errors)
        assert any("chapters" in e for e in errors)

    def test_validate_missing_paragraphs(self):
        st = StructuredText(
            title="Bad",
            chapters=[{"id": "1", "title": "ch", "order": 1}],  # no paragraphs
        )
        errors = st.validate()
        assert any("paragraphs" in e for e in errors)


# --- CTextParser ---

class TestCTextParser:
    def setup_method(self):
        self.parser = CTextParser()

    def test_parse_classic(self):
        api_resp = {
            "title": "學而",
            "fulltext": ["子曰：「學而時習之，不亦說乎？」", "有朋自遠方來，不亦樂乎？"],
            "author": "孔子",
            "dynasty": "周",
        }
        st = self.parser.parse_classic(api_resp, "path:analects/xue-er", "https://ctext.org/analects/xue-er/zh")
        assert st.title == "學而"
        assert st.content_type == "single_chapter"
        assert len(st.chapters) == 1
        assert st.chapters[0]["paragraphs"] == [
            "子曰：「學而時習之，不亦說乎？」",
            "有朋自遠方來，不亦樂乎？",
        ]
        assert st.metadata.get("dynasty") == "周"
        assert st.source["site"] == "ctext"

    def test_parse_classic_string_fulltext(self):
        """API sometimes returns fulltext as a string instead of list."""
        api_resp = {"title": "Test", "fulltext": "Single string content"}
        st = self.parser.parse_classic(api_resp, "path:test", "https://ctext.org/test")
        assert st.chapters[0]["paragraphs"] == ["Single string content"]

    def test_parse_wiki_book(self):
        chapters = [
            ("111", {"title": "卷一", "fulltext": ["段落一", "段落二"]}),
            ("222", {"title": "卷二", "fulltext": ["段落三"]}),
        ]
        meta = {"title": "四庫全書簡明目錄", "dynasty": "清", "volumes": 2}
        st = self.parser.parse_wiki_book(
            chapters, meta, "wiki-book:1347940",
            "https://ctext.org/wiki.pl?if=gb&res=1347940",
        )
        assert st.title == "四庫全書簡明目錄"
        assert st.content_type == "book_with_chapters"
        assert len(st.chapters) == 2
        assert st.chapters[0]["title"] == "卷一"
        assert st.chapters[0]["paragraphs"] == ["段落一", "段落二"]
        assert st.chapters[1]["id"] == "222"
        assert st.chapters[1]["order"] == 2

    def test_parse_html_text(self):
        parts = ["第一段", "第二段", "第三段"]
        st = self.parser.parse_html_text(parts, "測試頁面", "path:test", "https://ctext.org/test")
        assert st.title == "測試頁面"
        assert st.content_type == "single_chapter"
        assert st.chapters[0]["paragraphs"] == parts

    def test_source_fields(self):
        api_resp = {"title": "T", "fulltext": ["x"]}
        st = self.parser.parse_classic(api_resp, "path:t", "https://ctext.org/t")
        assert st.source["site"] == "ctext"
        assert st.source["url"] == "https://ctext.org/t"
        assert st.source["book_id"] == "path:t"
        assert "downloaded_at" in st.source


# --- Converters ---

class TestMarkdownConverter:
    def setup_method(self):
        self.converter = MarkdownConverter()

    def test_basic(self):
        data = {
            "title": "論語",
            "metadata": {
                "authors": [{"name": "孔子", "dynasty": "周", "role": "撰"}],
            },
            "chapters": [
                {"title": "學而", "paragraphs": ["子曰", "有朋"]},
                {"title": "為政", "paragraphs": ["子曰為政以德"]},
            ],
        }
        md = self.converter.convert(data)
        assert "# 論語" in md
        assert "[周] 孔子 撰" in md
        assert "## 學而" in md
        assert "子曰" in md
        assert "## 為政" in md

    def test_no_author(self):
        data = {"title": "Test", "chapters": [{"title": "Ch", "paragraphs": ["p"]}]}
        md = self.converter.convert(data)
        assert "# Test" in md
        assert ">" not in md  # no author line

    def test_empty_paragraphs_skipped(self):
        data = {
            "title": "T",
            "chapters": [{"title": "C", "paragraphs": ["a", "", "  ", "b"]}],
        }
        md = self.converter.convert(data)
        # empty/whitespace paragraphs should not appear
        lines = [l for l in md.split("\n") if l.strip()]
        assert "a" in lines
        assert "b" in lines


class TestPlainTextConverter:
    def setup_method(self):
        self.converter = PlainTextConverter()

    def test_basic(self):
        data = {
            "title": "Test",
            "chapters": [
                {"title": "Ch1", "paragraphs": ["line1", "line2"]},
                {"title": "Ch2", "paragraphs": ["line3"]},
            ],
        }
        txt = self.converter.convert(data)
        assert "Ch1" in txt
        assert "line1" in txt
        assert "Ch2" in txt
        assert "line3" in txt
        # No markdown markers
        assert "#" not in txt

    def test_no_title_chapter(self):
        data = {"chapters": [{"title": "", "paragraphs": ["only text"]}]}
        txt = self.converter.convert(data)
        assert "only text" in txt


# --- ShidianGuji Parser ---

class TestShidianGujiParser:
    def setup_method(self):
        self.parser = ShidianGujiParser()

    def test_parse_single_chapter(self):
        chapter_list = [
            {"id": "1", "title": "卷一", "content": "天地玄黃\n宇宙洪荒"},
        ]
        st = self.parser.parse(chapter_list, "book123", "https://www.shidianguji.com/book/book123")

        assert st.content_type == "single_chapter"
        assert len(st.chapters) == 1
        assert st.chapters[0]["title"] == "卷一"
        assert st.chapters[0]["paragraphs"] == ["天地玄黃", "宇宙洪荒"]
        assert st.chapters[0]["order"] == 1

    def test_parse_multiple_chapters(self):
        chapter_list = [
            {"id": "1", "title": "卷一", "content": "第一段\n第二段"},
            {"id": "2", "title": "卷二", "content": "第三段"},
            {"id": "3", "title": "卷三", "content": "第四段\n第五段\n第六段"},
        ]
        meta = {"title": "千字文", "author": "周兴嗣", "dynasty": "南梁", "category": "蒙学"}
        st = self.parser.parse(
            chapter_list, "book456",
            "https://www.shidianguji.com/book/book456", meta
        )

        assert st.content_type == "book_with_chapters"
        assert st.title == "千字文"
        assert st.metadata["authors"] == [{"name": "周兴嗣"}]
        assert st.metadata["dynasty"] == "南梁"
        assert st.metadata["category"] == "蒙学"
        assert len(st.chapters) == 3
        assert st.chapters[0]["paragraphs"] == ["第一段", "第二段"]
        assert st.chapters[2]["paragraphs"] == ["第四段", "第五段", "第六段"]

    def test_parse_skips_empty_content(self):
        chapter_list = [
            {"id": "1", "title": "卷一", "content": "有内容"},
            {"id": "2", "title": "卷二", "content": ""},
            {"id": "3", "title": "卷三", "content": "也有内容"},
        ]
        st = self.parser.parse(chapter_list, "book789", "https://example.com")

        assert len(st.chapters) == 2
        assert st.chapters[0]["title"] == "卷一"
        assert st.chapters[1]["title"] == "卷三"

    def test_parse_empty_chapters(self):
        st = self.parser.parse([], "empty", "https://example.com")

        assert len(st.chapters) == 0
        assert st.source["book_id"] == "empty"

    def test_source_fields(self):
        chapter_list = [{"title": "Test", "content": "text"}]
        st = self.parser.parse(
            chapter_list, "test_id", "https://www.shidianguji.com/book/test_id"
        )

        assert st.source["site"] == "shidianguji"
        assert st.source["book_id"] == "test_id"
        assert "downloaded_at" in st.source


# --- WikisourceParser ---

class TestWikisourceParser:
    def setup_method(self):
        self.parser = WikisourceParser()

    def test_parse_single_page(self):
        wikitext = "子曰：「學而時習之，不亦說乎？」\n\n有朋自遠方來，不亦樂乎？"
        st = self.parser.parse_single_page(
            wikitext, "論語/學而第一", "論語/學而第一",
            "https://zh.wikisource.org/wiki/論語/學而第一"
        )

        assert st.title == "論語"
        assert st.content_type == "single_chapter"
        assert len(st.chapters) == 1
        assert st.chapters[0]["title"] == "學而第一"
        assert len(st.chapters[0]["paragraphs"]) == 2
        assert "子曰" in st.chapters[0]["paragraphs"][0]

    def test_parse_single_page_no_slash(self):
        wikitext = "天地玄黃，宇宙洪荒。"
        st = self.parser.parse_single_page(
            wikitext, "千字文", "千字文",
            "https://zh.wikisource.org/wiki/千字文"
        )
        assert st.title == "千字文"
        assert st.chapters[0]["title"] == "千字文"

    def test_parse_book(self):
        pages = [
            {"title": "論語/學而第一", "pageid": 100, "wikitext": "子曰：學而\n\n有朋自遠方來"},
            {"title": "論語/為政第二", "pageid": 200, "wikitext": "子曰：為政以德"},
        ]
        st = self.parser.parse_book(
            pages, "論語", "論語",
            "https://zh.wikisource.org/wiki/論語"
        )

        assert st.title == "論語"
        assert st.content_type == "book_with_chapters"
        assert len(st.chapters) == 2
        assert st.chapters[0]["title"] == "學而第一"
        assert st.chapters[0]["id"] == "100"
        assert st.chapters[0]["order"] == 1
        assert st.chapters[1]["title"] == "為政第二"
        assert st.chapters[1]["order"] == 2

    def test_parse_book_single_chapter(self):
        pages = [
            {"title": "千字文/全文", "pageid": 1, "wikitext": "天地玄黃"},
        ]
        st = self.parser.parse_book(pages, "千字文", "千字文", "https://example.com")
        assert st.content_type == "single_chapter"

    def test_parse_book_empty_pages(self):
        st = self.parser.parse_book([], "Empty", "Empty", "https://example.com")
        assert len(st.chapters) == 0
        assert st.source["site"] == "wikisource"

    def test_parse_book_skips_empty_wikitext(self):
        pages = [
            {"title": "書/卷一", "pageid": 1, "wikitext": "有內容"},
            {"title": "書/卷二", "pageid": 2, "wikitext": ""},
            {"title": "書/卷三", "pageid": 3, "wikitext": "也有內容"},
        ]
        st = self.parser.parse_book(pages, "書", "書", "https://example.com")
        assert len(st.chapters) == 2
        assert st.chapters[0]["title"] == "卷一"
        assert st.chapters[1]["title"] == "卷三"

    def test_wikitext_strip_wiki_links(self):
        wikitext = "[[孔子|孔丘]]說了[[論語]]"
        paragraphs = self.parser._wikitext_to_paragraphs(wikitext)
        assert paragraphs == ["孔丘說了論語"]

    def test_wikitext_strip_templates(self):
        wikitext = "{{header2|title=Test}}正文開始\n\n{{另|原文|異文}}結束"
        paragraphs = self.parser._wikitext_to_paragraphs(wikitext)
        assert len(paragraphs) >= 1
        assert "正文開始" in paragraphs[0]
        # header2 template should be stripped
        assert "header2" not in " ".join(paragraphs)

    def test_wikitext_strip_html_tags(self):
        wikitext = "<div>段落一</div>\n\n<span>段落二</span>"
        paragraphs = self.parser._wikitext_to_paragraphs(wikitext)
        assert "段落一" in paragraphs[0]
        assert "段落二" in paragraphs[1]
        assert "<div>" not in " ".join(paragraphs)

    def test_wikitext_strip_refs(self):
        wikitext = "正文<ref>這是注釋</ref>繼續"
        paragraphs = self.parser._wikitext_to_paragraphs(wikitext)
        assert paragraphs == ["正文繼續"]

    def test_wikitext_strip_bold_italic(self):
        wikitext = "'''粗體'''和''斜體''文字"
        paragraphs = self.parser._wikitext_to_paragraphs(wikitext)
        assert paragraphs == ["粗體和斜體文字"]

    def test_wikitext_onlyinclude(self):
        wikitext = "不要的部分<onlyinclude>要的部分</onlyinclude>也不要"
        paragraphs = self.parser._wikitext_to_paragraphs(wikitext)
        assert paragraphs == ["要的部分"]

    def test_wikitext_strip_categories(self):
        wikitext = "正文\n\n[[Category:古文]][[分類:經部]]"
        paragraphs = self.parser._wikitext_to_paragraphs(wikitext)
        assert paragraphs == ["正文"]

    def test_wikitext_empty(self):
        assert self.parser._wikitext_to_paragraphs("") == []
        assert self.parser._wikitext_to_paragraphs(None) == []

    def test_source_fields(self):
        st = self.parser.parse_single_page(
            "text", "Test", "Test",
            "https://zh.wikisource.org/wiki/Test"
        )
        assert st.source["site"] == "wikisource"
        assert st.source["book_id"] == "Test"
        assert "downloaded_at" in st.source

    def test_metadata_license(self):
        st = self.parser.parse_single_page(
            "text", "Test", "Test", "https://example.com"
        )
        assert st.metadata.get("license") == "CC BY-SA 4.0"
