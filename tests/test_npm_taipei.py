"""Offline tests for the NPM (國立故宮博物院 Open Data) adapter."""

import json
import re
from pathlib import Path

import pytest

from bookget.adapters import get_adapter
from bookget.adapters.other.taiwan import (
    PalaceMuseumTaipeiAdapter, clean_html_text, parse_detail_page,
)

FIX = Path(__file__).parent / "fixtures" / "npm"


@pytest.fixture
def adapter():
    return PalaceMuseumTaipeiAdapter()


def _load(name):
    return (FIX / name).read_text(encoding="utf-8")


class TestRouting:
    @pytest.mark.parametrize("url,book_id", [
        ("https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=1528&dep=P&mode=full", "P1528"),
        ("https://digitalarchive.npm.gov.tw/opendata/Pub/Detail/1528?dep=P", "P1528"),
        ("https://digitalarchive.npm.gov.tw/opendata/Pub/DetailEng/40?dep=P", "P40"),
        ("https://digitalarchive.npm.gov.tw/opendata/Collection/Detail?id=11&dep=U", "U11"),
        ("https://digitalarchive.npm.gov.tw/opendata/IIIFViewer?id=1528&dep=P&imageName=", "P1528"),
        ("https://digitalarchive.npm.gov.tw/opendata/Integrate/GetJson?cid=1528&dept=P&imageName=", "P1528"),
    ])
    def test_extract_book_id(self, adapter, url, book_id):
        assert adapter.extract_book_id(url) == book_id

    def test_registry_routes_to_npm(self):
        a = get_adapter("https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=1528&dep=P")
        assert a is not None and a.site_id == "npm_taipei"

    def test_urls(self, adapter):
        assert adapter.detail_url("P1528").endswith("/opendata/Pub/Detail?id=1528&dep=P&mode=full")
        assert adapter.manifest_url("U11").endswith("/opendata/Integrate/GetJson?cid=11&dept=U&imageName=")
        assert adapter.image_service("K2D000156N000000012PAA") == \
            "https://iiifod.npm.gov.tw/iiif/2/K2D%2FK2D000156N000000012PAA"


class TestParser:
    def test_clean_html_text(self):
        assert clean_html_text("<b>a</b>&nbsp;b&#12288;c<br>d") == "a b　c d"

    def test_parse_detail_p1528(self):
        d = parse_detail_page(_load("detail_P1528.html"))
        assert d["title"].startswith("清紀昀欽定四庫全書簡明目錄")
        assert d["fields"]["文物統一編號"].startswith("中書")
        assert len(d["image_names"]) == 12
        assert "details-1" in d["sections"]
        assert d["attribution"]

    def test_parse_detail_album_leaf(self):
        d = parse_detail_page(_load("detail_P16797.html"))
        assert d["fields"]["文物統一編號"] == "故帖000156N000000012"
        assert d["fields"]["文物統一編號（其他）"] == "故帖000156N000000013"
        assert d["image_names"] == ["K2D000156N000000012PAA", "K2D000156N000000013PAA"]
        assert d["sections"]["details-1"]["title"] == "基本資料"

    def test_parse_sections_p1528(self):
        d = parse_detail_page(_load("detail_P1528.html"))
        sec = d["sections"]
        assert sec["details-5"]["title"] == "印記資料" and len(sec["details-5"]["rows"]) == 6
        assert sec["details-4"]["rows"] and len(sec["details-4"]["rows"][0]) >= 6     # 題跋: folded seal columns
        assert sec["details-2"]["rows"][0][1]                                          # 典藏尺寸 value


class TestMetadataAndImages:
    @pytest.mark.asyncio
    async def test_metadata_from_fixture(self, adapter):
        adapter._detail_cache["P16797"] = parse_detail_page(_load("detail_P16797.html"))
        md = await adapter.get_metadata("P16797")
        assert md.call_number == "故帖000156N000000012"
        assert md.collection_unit == "國立故宮博物院"
        assert md.license == "CC BY 4.0"
        assert [c.name for c in md.creators] == ["王獻之"]
        assert md.dynasty == "宋"
        assert md.raw_metadata["image_names"]
        assert "sections" in md.raw_metadata

    @pytest.mark.asyncio
    async def test_image_list_from_manifest(self, adapter, monkeypatch):
        manifest = json.loads(_load("manifest_P1528.json"))
        adapter._detail_cache["P1528"] = parse_detail_page(_load("detail_P1528.html"))

        async def fake_manifest(book_id):
            return manifest
        monkeypatch.setattr(adapter, "get_iiif_manifest", fake_manifest)
        res = await adapter.get_image_list("P1528")
        assert len(res) == 12
        assert res[0].url.endswith("/full/full/0/default.jpg")
        assert res[0].filename == "001_C2B000007N000000000PAA.jpg"
        assert res[0].iiif_service_id.startswith("https://iiifod.npm.gov.tw/iiif/2/")
        assert [r.order for r in res] == list(range(1, 13))

    @pytest.mark.asyncio
    async def test_image_list_gallery_fallback(self, adapter, monkeypatch):
        """GetJson returns an empty body for some records: fall back to the page gallery."""
        adapter._detail_cache["P16797"] = parse_detail_page(_load("detail_P16797.html"))

        async def empty(book_id):
            return None
        monkeypatch.setattr(adapter, "get_iiif_manifest", empty)
        res = await adapter.get_image_list("P16797")
        assert [r.page for r in res] == ["K2D000156N000000012PAA", "K2D000156N000000013PAA"]


class TestSearchAndAlbum:
    def test_parse_search_page(self):
        from bookget.adapters.other.taiwan import parse_search_page
        res = parse_search_page(_load("search_gutie000156.html"))
        assert res["page_count"] == 1 and len(res["items"]) == 31
        assert res["items"][0] == ("16764", "P", "宋榻大觀帖（九）　冊　晉王獻之相過帖")

    def test_work_title(self):
        from bookget.adapters.other.taiwan import work_title
        assert work_title("宋榻大觀帖（九）　冊　晉王獻之吳興帖") == "宋榻大觀帖（九） 冊"
        assert work_title("清紀昀欽定四庫全書簡明目錄（經部）　卷 Catalogue") == "清紀昀欽定四庫全書簡明目錄（經部） 卷"
        assert work_title("元趙孟頫書") == "元趙孟頫書"

    @pytest.mark.asyncio
    async def test_search(self, adapter, monkeypatch):
        seen = {}

        async def fake_post(url, payload):
            seen.update(payload)
            return _load("search_gutie000156.html")
        monkeypatch.setattr(adapter, "_post_json_text", fake_post)
        res = await adapter.search("category:法帖", limit=50, offset=100)
        assert seen["RegisterType"] == "法帖" and seen["SearchContent"] is None
        assert seen["PageInfo"] == {"PageIndex": 3, "PageSize": 50, "PageCount": 1}
        assert len(res.results) == 31 and res.results[0].page_id == 16764
        assert res.results[0].url.endswith("Detail?id=16764&dep=P&mode=full") and not res.has_more
        await adapter.search("故帖000156")
        assert seen["SearchContent"] == "故帖000156" and seen["RegisterType"] is None

    @pytest.mark.asyncio
    async def test_album_mode(self, adapter, monkeypatch):
        """Album mode expands a leaf to its work via the search + sibling detail pages."""
        pages = {"16797": _load("detail_P16797.html"), "16764": _load("detail_P16764.html")}

        async def fake_get(url, retries=4):
            m = re.search(r"[?&]id=(\d+)", url) or re.search(r"/Detail(?:Eng)?/(\d+)", url)
            if "GetJson" in url:
                return ""
            if "DetailEng" in url:
                return _load("detail_en_P16797.html")
            return pages[m.group(1)]

        async def fake_search_all(query):
            from bookget.models.search import SearchResult
            assert query == "故帖000156"
            return [SearchResult(title="a", page_id=16764, snippet="P16764"), SearchResult(title="b", page_id=16797, snippet="P16797")]
        monkeypatch.setattr(adapter, "_get_text", fake_get)
        monkeypatch.setattr(adapter, "search_all", fake_search_all)
        adapter.album_mode = True
        md = await adapter.get_metadata("P16797")
        assert md.title == "宋榻大觀帖（九） 冊" and md.call_number == "故帖000156"
        assert md.raw_metadata["kind"] == "work" and len(md.raw_metadata["records"]) == 2
        assert md.raw_metadata["album_id"] == "P16764"
        res = await adapter.get_image_list("P16797")
        assert [r.page for r in res] == ["K2D000156N000000001PAA", "K2D000156N000000012PAA", "K2D000156N000000013PAA"]
        assert res[0].volume == "故帖000156N000000001" and res[2].volume == "故帖000156N000000012"
        assert res[0].filename == "001_K2D000156N000000001PAA.jpg"

    @pytest.mark.asyncio
    async def test_single_record_keeps_english_sections(self, adapter, monkeypatch):
        async def fake_get(url, retries=4):
            return _load("detail_en_P16797.html") if "DetailEng" in url else _load("detail_P16797.html")
        monkeypatch.setattr(adapter, "_get_text", fake_get)
        md = await adapter.get_metadata("P16797")
        assert md.raw_metadata["kind"] == "record"
        assert md.raw_metadata["sections_en"]["details-1"]["rows"][0][0]


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_album():
    """Real site: search + sibling records for 宋榻大觀帖（九）冊 (31 leaf records, 18 images)."""
    a = PalaceMuseumTaipeiAdapter()
    a.album_mode = True
    try:
        md = await a.get_metadata("P16797")
        assert md.title == "宋榻大觀帖（九） 冊" and md.call_number == "故帖000156"
        assert len(md.raw_metadata["records"]) >= 30
        res = await a.get_image_list("P16797")
        assert len(res) >= 18 and res[0].page == "K2D000156N000000001PAA"
        hits = await a.search("category:法帖", limit=20)
        assert len(hits.results) == 20 and hits.has_more
    finally:
        await a.close()
