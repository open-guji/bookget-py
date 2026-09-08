# Opt-in LIVE download-path tests (marked `live`, deselected by default).
#
#     pytest -m live tests/test_live_download.py
#
# Driven by tests/fixtures/live_urls.yaml. Each item runs the real path:
#   extract_book_id -> get_metadata -> get_image_list / get_structured_text
# against the actual site, to confirm download functionality still works.
#
# Network-dependent and intentionally lightweight (one item per site). Not run
# in the default offline suite; run manually or on a schedule.

import pathlib

import pytest
import yaml

from bookget.adapters.registry import get_adapter

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "live_urls.yaml"
_ITEMS = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))["items"]


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item", _ITEMS, ids=[f"{i['site_id']}" for i in _ITEMS]
)
async def test_live_download_path(item):
    adapter = get_adapter(item["url"])
    assert adapter is not None, f"no adapter for {item['url']}"
    try:
        book_id = adapter.extract_book_id(item["url"])
        assert book_id, f"empty book_id for {item['url']}"

        metadata = await adapter.get_metadata(book_id)
        assert metadata is not None
        assert metadata.title, f"empty title for {item['url']}"
        if item.get("title_contains"):
            assert item["title_contains"] in metadata.title, (
                f"title {metadata.title!r} lacks {item['title_contains']!r}"
            )

        if item["kind"] == "images":
            images = await adapter.get_image_list(book_id)
            min_images = item.get("min_images", 1)
            assert len(images) >= min_images, (
                f"got {len(images)} images, expected >= {min_images}"
            )
            assert images[0].url.startswith("http")
        elif item["kind"] == "text":
            st = await adapter.get_structured_text(book_id)
            assert st is not None, "get_structured_text returned None"
            assert st.chapters, "structured text has no chapters"
            # at least one chapter has some paragraph text
            assert any(c.get("paragraphs") for c in st.chapters)
        elif item["kind"] == "tiled":
            # tiled (Zoomify) sites: verify get_image_list + stitch the FIRST
            # page end-to-end into a full image.
            import pathlib
            import tempfile
            from PIL import Image
            from bookget.models.manifest import (
                ManifestNode, NodeType, NodeStatus)

            images = await adapter.get_image_list(book_id)
            assert len(images) >= item.get("min_images", 1)
            node = ManifestNode(id="t", title="t", node_type=NodeType.VOLUME,
                                status=NodeStatus.DISCOVERED)
            node.source_data = {"images": [
                {"url": images[0].url, "filename": "0001.jpg"}]}
            with tempfile.TemporaryDirectory() as td:
                await adapter.download_node(book_id, node, pathlib.Path(td))
                f = pathlib.Path(td) / "0001.jpg"
                assert f.exists() and f.stat().st_size > 50000, "stitched image too small"
                w, h = Image.open(f).size
                assert w >= 1000 and h >= 1000, f"unexpected dims {w}x{h}"
        else:
            pytest.fail(f"unknown kind: {item['kind']}")
    finally:
        await adapter.close()
