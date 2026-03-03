# Tests for utility functions

import pytest
from bookget.utils import (
    extract_domain,
    extract_path,
    extract_query_param,
    sanitize_filename,
    normalize_chinese_text,
    parse_dynasty,
    format_creators,
)


class TestURLExtraction:
    """Tests for URL extraction utilities."""
    
    def test_extract_domain(self):
        assert extract_domain("https://guji.nlc.cn/book/123") == "guji.nlc.cn"
        assert extract_domain("https://www.ctext.org/analects") == "www.ctext.org"
        assert extract_domain("http://dl.ndl.go.jp/pid/123") == "dl.ndl.go.jp"
        assert extract_domain("invalid") == ""
    
    def test_extract_path(self):
        assert extract_path("https://example.com/book/123") == "/book/123"
        assert extract_path("https://example.com") == ""
        assert extract_path("https://example.com/") == "/"
    
    def test_extract_query_param(self):
        url = "https://example.com?id=123&page=5"
        assert extract_query_param(url, "id") == "123"
        assert extract_query_param(url, "page") == "5"
        assert extract_query_param(url, "missing") is None


class TestSanitizeFilename:
    """Tests for filename sanitization."""
    
    def test_removes_illegal_chars(self):
        assert sanitize_filename('file:name') == 'file_name'
        assert sanitize_filename('file/name') == 'file_name'
        assert sanitize_filename('file<name>') == 'file_name_'
    
    def test_handles_unicode(self):
        assert sanitize_filename('四库全书') == '四库全书'
        assert sanitize_filename('論語.txt') == '論語.txt'
    
    def test_length_limit(self):
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=100)
        assert len(result) <= 100
    
    def test_preserves_extension(self):
        long_name = "a" * 300 + ".jpg"
        result = sanitize_filename(long_name, max_length=100)
        assert result.endswith(".jpg")
    
    def test_empty_becomes_unnamed(self):
        assert sanitize_filename("") == "unnamed"
        assert sanitize_filename("...") == "unnamed"


class TestNormalizeChineseText:
    """Tests for Chinese text normalization."""
    
    def test_removes_whitespace(self):
        assert normalize_chinese_text("四 库 全 书") == "四库全书"
    
    def test_traditional_to_simplified(self):
        result = normalize_chinese_text("國家圖書館")
        assert "国" in result
        assert "图" in result
        assert "书" in result
        assert "馆" in result


class TestParseDynasty:
    """Tests for dynasty/date parsing."""
    
    def test_bracketed_dynasty(self):
        dynasty, year = parse_dynasty("[宋]")
        assert dynasty == "宋"
    
    def test_dynasty_with_year(self):
        dynasty, year = parse_dynasty("清乾隆四十六年 (1781)")
        assert dynasty == "清"
        assert year == "1781"
    
    def test_simple_dynasty(self):
        dynasty, year = parse_dynasty("明嘉靖")
        assert dynasty == "明"
        assert year == ""


class TestFormatCreators:
    """Tests for creator formatting."""
    
    def test_single_creator(self):
        creators = [{"name": "李白", "dynasty": "唐", "role": "撰"}]
        result = format_creators(creators)
        assert "[唐]" in result
        assert "李白" in result
        assert "撰" in result
    
    def test_multiple_creators(self):
        creators = [
            {"name": "孔子", "role": ""},
            {"name": "朱熹", "dynasty": "宋", "role": "注"}
        ]
        result = format_creators(creators)
        assert "孔子" in result
        assert "朱熹" in result
        assert ";" in result
    
    def test_empty_creators(self):
        assert format_creators([]) == ""
