# Tests for the shared CJK title/author matching module.
#
# This logic was previously duplicated in the CText and Shidianguji adapters;
# it now lives in bookget.shared.cjk_match. These tests lock the behavior both
# adapters depend on for search/match_book.

import pytest

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


class TestOpenCCIsAvailable:
    """OpenCC is a declared dependency, not an optional nicety.

    It used to be used by this module but declared nowhere in pyproject, so
    pip-installed users silently lost 繁简 matching (论语 stopped matching
    論語) with no error at all. These tests fail loudly if that regresses.
    """

    def test_opencc_importable(self):
        import opencc  # noqa: F401

    def test_s2t_converter_usable(self):
        assert m._get_s2t() is not None
        assert m._convert_s2t("论语") == "論語"

    def test_variant_map_is_not_empty(self):
        # Modern OpenCC wheels ship only binary .ocd2 dicts, so the original
        # `dictionary/*.txt` parsing silently produced an EMPTY map even when
        # OpenCC was installed — making 异体字 normalization a no-op.
        assert len(m._get_variant_map()) > 0

    @pytest.mark.parametrize("variant,standard", [
        ("史徴", "史徵"),   # JP variant (jp2t)
        ("竜", "龍"),
        ("沢", "澤"),
    ])
    def test_jp_variants_normalize(self, variant, standard):
        assert m.normalize_variants(variant) == m.normalize_variants(standard)


class TestYuVariantsAllMatch:
    """餘 / 余 / 馀 are three forms of one word and must be interchangeable.

    CJK_VARIANTS used to carry a duplicate '餘' key whose second value
    silently overwrote the first (a dict holds one value per key). The
    duplicate is gone; these assertions pin the behavior that matters.
    """

    @pytest.mark.parametrize("a,b", [
        ("餘杭", "余杭"),
        ("餘杭", "馀杭"),
        ("余杭", "馀杭"),
    ])
    def test_interchangeable(self, a, b):
        assert m.title_matches(a, [b])

    def test_no_duplicate_keys_in_variant_table(self):
        # Guard the source itself: a repeated key is invisible at runtime.
        import ast
        import inspect
        src = inspect.getsource(m)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "CJK_VARIANTS" for t in node.targets
            ):
                keys = [k.value for k in node.value.keys
                        if isinstance(k, ast.Constant)]
                dupes = {k for k in keys if keys.count(k) > 1}
                assert not dupes, f"duplicate keys in CJK_VARIANTS: {dupes}"
