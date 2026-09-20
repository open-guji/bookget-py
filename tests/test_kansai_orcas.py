"""Offline tests for the Kansai University KU-ORCAS adapter."""

import pytest

from bookget.adapters.iiif.kansai_orcas import KansaiOrcasAdapter
from bookget.exceptions import MetadataExtractionError

MANIFEST = ("https://www.iiif.ku-orcas.kansai-u.ac.jp/iiif/books/"
            "002720833/manifest.json")


class TestExtractBookId:
    @pytest.mark.parametrize("url", [
        "https://www.iiif.ku-orcas.kansai-u.ac.jp/books/002720833",
        "https://www.iiif.ku-orcas.kansai-u.ac.jp/iiif/books/002720833/manifest.json",
        # Viewer links carry the manifest in the query string.
        "https://www.iiif.ku-orcas.kansai-u.ac.jp/libraries/mirador/mirador.html"
        "?manifest=" + MANIFEST,
    ])
    def test_all_url_forms(self, url):
        assert KansaiOrcasAdapter().extract_book_id(url) == "002720833"

    def test_non_item_url(self):
        with pytest.raises(MetadataExtractionError):
            KansaiOrcasAdapter().extract_book_id(
                "https://www.iiif.ku-orcas.kansai-u.ac.jp/news")


class TestManifestUrl:
    def test_template(self):
        assert KansaiOrcasAdapter().get_manifest_url("002720833") == MANIFEST
