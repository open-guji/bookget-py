# Offline unit tests for the Zoomify tile-layout math (bookget/downloaders/tiles.py).
# Validated against a real TNM ImageProperties.xml:
#   WIDTH=5760 HEIGHT=3840 TILESIZE=256 NUMTILES=474

from bookget.downloaders.tiles import (
    parse_image_properties,
    zoomify_top_tier,
    total_tiles,
)


def test_parse_image_properties():
    xml = ('<IMAGE_PROPERTIES WIDTH="5760" HEIGHT="3840" NUMTILES="474" '
           'NUMIMAGES="1" VERSION="1.8" TILESIZE="256" />')
    assert parse_image_properties(xml) == {
        "width": 5760, "height": 3840, "tilesize": 256,
    }


def test_parse_image_properties_default_tilesize():
    xml = '<IMAGE_PROPERTIES WIDTH="100" HEIGHT="200" />'
    assert parse_image_properties(xml)["tilesize"] == 256


def test_total_tiles_matches_numtiles():
    # The total over all tiers must equal Zoomify's NUMTILES.
    assert total_tiles(5760, 3840, 256) == 474


def test_top_tier_layout():
    top, cols, rows, tilegroup = zoomify_top_tier(5760, 3840, 256)
    # tiers: (180,120)(360,240)(720,480)(1440,960)(2880,1920)(5760,3840)
    assert top == 5
    assert (cols, rows) == (23, 15)
    # lower tiers hold 1+2+6+24+96 = 129 tiles; top-tier indices start at 129
    assert tilegroup(0, 0) == 0          # 129 // 256
    assert tilegroup(22, 14) == 1        # (129 + 14*23 + 22)=473 → 473//256


def test_single_tile_image():
    # an image smaller than one tile → top tier 0, 1x1
    top, cols, rows, _ = zoomify_top_tier(200, 150, 256)
    assert (top, cols, rows) == (0, 1, 1)
    assert total_tiles(200, 150, 256) == 1
