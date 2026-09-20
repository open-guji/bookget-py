# Offline smoke test: every adapter's URL routing + ID extraction.
#
# Driven by tests/fixtures/site_urls.yaml (real-world URL shapes from the
# bookget Wiki + adapter docstrings). No network access — this guards URL
# routing and extract_book_id against regressions as new adapters are added.

import pathlib

import pytest
import yaml

from bookget.adapters.registry import AdapterRegistry

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "site_urls.yaml"


def _load_sites():
    data = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    return data["sites"]


_SITES = _load_sites()

# Flatten to (site_id, url) pairs — every URL shape is tested independently.
_URL_CASES = [
    (site["site_id"], url)
    for site in _SITES
    for url in site["urls"]
]


@pytest.mark.parametrize(
    "site_id,url", _URL_CASES, ids=[f"{s}:{u}" for s, u in _URL_CASES]
)
def test_url_routes_to_expected_adapter(site_id, url):
    """get_for_url(url) resolves to the adapter declared in the fixture."""
    cls = AdapterRegistry.get_for_url(url)
    assert cls is not None, f"no adapter routed for {url}"
    assert cls.site_id == site_id, (
        f"{url} routed to {cls.site_id}, expected {site_id}"
    )


@pytest.mark.parametrize(
    "site_id,url", _URL_CASES, ids=[f"{s}:{u}" for s, u in _URL_CASES]
)
def test_extract_book_id_nonempty(site_id, url):
    """extract_book_id returns a non-empty string for every example URL."""
    cls = AdapterRegistry.get_for_url(url)
    assert cls is not None
    book_id = cls().extract_book_id(url)
    assert isinstance(book_id, str) and book_id, (
        f"extract_book_id returned {book_id!r} for {url}"
    )


def test_fixture_covers_all_routable_adapters():
    """Every registered adapter that matches by domain should have a fixture
    entry (keeps the smoke test honest as new adapters are added).

    Adapters that match purely structurally (e.g. generic_iiif) are exempt.
    """
    exempt = {"generic_iiif"}
    fixture_ids = {e["site_id"] for e in _SITES}
    registered = {a["id"] for a in AdapterRegistry.list_adapters()}
    missing = registered - fixture_ids - exempt
    assert not missing, f"adapters without a site_urls.yaml entry: {sorted(missing)}"


class TestPdfOnlyAdaptersAreDiscoverable:
    """PDF-only sites must not be skipped by manifest discovery.

    `BaseSiteAdapter.discover` used to gate the file listing on
    supports_images alone, but PDF-only sites (nlc_read) return their files
    from the same get_image_list() while declaring supports_images = False,
    so they discovered an empty manifest.
    """

    def test_nlc_read_declares_pdf_not_images(self):
        cls = AdapterRegistry.get_by_id("nlc_read")
        assert cls is not None
        assert cls.supports_pdf is True
        assert cls.supports_images is False

    def test_every_adapter_offers_something_downloadable(self):
        # An adapter that declares none of these would silently discover
        # nothing at all.
        for info in AdapterRegistry.list_adapters():
            cls = AdapterRegistry.get_by_id(info["id"])
            assert (
                cls.supports_images
                or cls.supports_pdf
                or cls.supports_text
            ), f"{info['id']} declares no downloadable resource type"
