# Tests for batch download support in the `download` command (issue #2).
#
# These are offline: they exercise URL collection, de-duplication, the
# url-file parser and the directory-name sanitizer, none of which touch
# the network.

import argparse

import pytest

from bookget.main import (
    _safe_dirname,
    collect_download_urls,
    read_url_file,
)


def make_args(**kw):
    """Build an argparse.Namespace shaped like the `download` parser's."""
    base = {"url": [], "url_file": None, "retry_failed": None}
    base.update(kw)
    return argparse.Namespace(**base)


class TestReadUrlFile:
    def test_reads_one_per_line(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://a.test/1\nhttps://b.test/2\n", encoding="utf-8")
        assert read_url_file(str(f)) == ["https://a.test/1", "https://b.test/2"]

    def test_skips_comments_and_blanks(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text(
            "# a comment\n\nhttps://a.test/1\n   \n# another\nhttps://b.test/2\n",
            encoding="utf-8",
        )
        assert read_url_file(str(f)) == ["https://a.test/1", "https://b.test/2"]

    def test_failed_urls_file_round_trips(self, tmp_path):
        # The failed_urls.txt we write annotates each URL with a '# error'
        # line; feeding it back to --retry-failed must yield only the URLs.
        f = tmp_path / "failed_urls.txt"
        f.write_text(
            "# URLs that failed in the last batch.\n"
            "# No adapter found for URL: https://x.invalid/1\n"
            "https://x.invalid/1\n",
            encoding="utf-8",
        )
        assert read_url_file(str(f)) == ["https://x.invalid/1"]


class TestCollectDownloadUrls:
    def test_positional_urls(self):
        args = make_args(url=["https://a.test/1", "https://b.test/2"])
        assert collect_download_urls(args) == ["https://a.test/1", "https://b.test/2"]

    def test_empty_when_nothing_given(self):
        assert collect_download_urls(make_args()) == []

    def test_merges_file_and_positional(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://b.test/2\n", encoding="utf-8")
        args = make_args(url=["https://a.test/1"], url_file=str(f))
        assert collect_download_urls(args) == ["https://a.test/1", "https://b.test/2"]

    def test_dedupes_preserving_order(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://a.test/1\nhttps://c.test/3\n", encoding="utf-8")
        args = make_args(url=["https://a.test/1", "https://b.test/2"], url_file=str(f))
        assert collect_download_urls(args) == [
            "https://a.test/1",
            "https://b.test/2",
            "https://c.test/3",
        ]


class TestSafeDirname:
    @pytest.mark.parametrize("raw,expected", [
        # CText book ids contain ':', which is illegal in Windows paths and
        # used to fail the whole download with WinError 267.
        ("path:analects", "path_analects"),
        ("SBCK001", "SBCK001"),
        ("https://ctext.org/analects", "ctext.org_analects"),
    ])
    def test_sanitizes(self, raw, expected):
        assert _safe_dirname(raw) == expected

    def test_never_empty(self):
        assert _safe_dirname("///") == "book"

    def test_is_bounded(self):
        assert len(_safe_dirname("x" * 500)) <= 80

    def test_result_has_no_path_separators(self):
        for raw in ("path:analects", "a/b/c", "a\b", "http://x.test/a/b"):
            out = _safe_dirname(raw)
            assert "/" not in out and "\\" not in out and ":" not in out
