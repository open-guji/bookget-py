# Tests for the shared CJK title/author matching module.
#
# This logic was previously duplicated in the CText and Shidianguji adapters;
# it now lives in bookget.shared.cjk_match. These tests lock the behavior both
# adapters depend on for search/match_book.

from bookget.shared import cjk_match as m


class TestGenerateTitleVariants:
    def test_includes_original(self):
        assert "周易" in m.generate_title_variants("周易")

    def test_single_char_variant_zhu(self):
        # 注 <-> 註 is a non-s/t variant pair handled by the built-in table
        assert "春秋註" in m.generate_title_variants("春秋注")

    def test_simplified_traditional(self):
        # OpenCC s2t/t2s round-trip
        variants = m.generate_title_variants("论语")
        assert "論語" in variants

    def test_removable_prefix(self):
        # 欽定 prefix should be strippable
        variants = m.generate_title_variants("欽定四庫全書")
        assert "四庫全書" in variants


class TestTitleMatches:
    def test_simplified_matches_traditional(self):
        assert m.title_matches("论语", ["論語"])

    def test_traditional_matches_simplified(self):
        assert m.title_matches("論語", ["论语"])

    def test_variant_char(self):
        # 注<->註 expansion happens in generate_title_variants, then
        # title_matches compares against the expanded list (real usage).
        variants = m.generate_title_variants("春秋注")
        assert m.title_matches("春秋註", variants)

    def test_no_match(self):
        assert not m.title_matches("孟子", ["論語"])

    def test_strict_blocks_prefix(self):
        # "論" is a 1-char prefix; strict mode must not match
        assert not m.title_matches("論語集注", ["論"])

    def test_nonstrict_allows_prefix(self):
        assert m.title_matches("論語集注", ["論語"], strict=False)


class TestAuthorMatches:
    def test_role_word_stripped(self):
        assert m.author_matches("朱熹撰", ["朱熹"])

    def test_simplified_traditional(self):
        assert m.author_matches("欧阳修", ["歐陽脩"]) or m.author_matches(
            "歐陽修", ["欧阳修"])

    def test_accepts_list(self):
        assert m.author_matches(["王弼", "韓康伯"], ["韓康伯"])

    def test_no_match(self):
        assert not m.author_matches("朱熹", ["王弼"])


class TestSurnameMatches:
    def test_combined_string_split(self):
        # "（宋）朱熹" should yield surname 朱
        assert m.surname_matches("（宋）朱熹", ["朱子"])

    def test_list_input(self):
        assert m.surname_matches(["王弼"], ["王安石"])

    def test_no_shared_surname(self):
        assert not m.surname_matches("朱熹", ["王弼"])


class TestParseAuthorDynasty:
    def test_basic(self):
        assert m.parse_author_dynasty("（宋）朱熹") == ("宋", "朱熹")

    def test_with_pipe(self):
        assert m.parse_author_dynasty("（漢）鄭玄 | 原典") == ("漢", "鄭玄")

    def test_no_dynasty(self):
        assert m.parse_author_dynasty("朱熹") == ("", "朱熹")

    def test_empty(self):
        assert m.parse_author_dynasty("") == ("", "")
