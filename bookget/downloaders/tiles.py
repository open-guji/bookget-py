# Tiled-image (Zoomify) downloader + stitcher.
#
# Many viewers (东京国立博物馆 webarchives.tnm.jp, 省级方志四川/云南/湖北/江苏 等)
# serve images as Zoomify tile pyramids instead of whole images:
#   {base}/ImageProperties.xml            → <IMAGE_PROPERTIES WIDTH=.. HEIGHT=.. TILESIZE=.. NUMTILES=.. />
#   {base}/TileGroup{g}/{tier}-{col}-{row}.jpg
# To get the full-resolution page we fetch every tile of the top tier and
# stitch them into one image with Pillow.
#
# Zoomify layout (validated: WIDTH=5760 HEIGHT=3840 TILESIZE=256 → NUMTILES=474):
#   tiers are built by halving the image until it fits in a single tile;
#   tier 0 = smallest, top tier = full resolution. Tiles are numbered with a
#   global running index (tier 0 first), and TileGroup = floor(index / 256).

from __future__ import annotations

import asyncio
import math
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

import aiohttp

from ..logger import logger

# group folder holds 256 tiles regardless of pixel tile size
_GROUP_SIZE = 256


def parse_image_properties(xml: str) -> Optional[dict]:
    """Parse a Zoomify ImageProperties.xml string → {width,height,tilesize}."""
    w = re.search(r'WIDTH=["\'](\d+)', xml)
    h = re.search(r'HEIGHT=["\'](\d+)', xml)
    t = re.search(r'TILESIZE=["\'](\d+)', xml)
    if not (w and h):
        return None
    return {
        "width": int(w.group(1)),
        "height": int(h.group(1)),
        "tilesize": int(t.group(1)) if t else 256,
    }


def _tier_dims(width: int, height: int, tilesize: int) -> list[tuple[int, int]]:
    """Pyramid dims, smallest tier first (last = full resolution)."""
    dims = [(width, height)]
    w, h = width, height
    while w > tilesize or h > tilesize:
        w = (w + 1) // 2
        h = (h + 1) // 2
        dims.append((w, h))
    dims.reverse()
    return dims


def zoomify_top_tier(width: int, height: int, tilesize: int = 256):
    """Return (top_tier, cols, rows, tilegroup_fn) for the full-resolution tier."""
    dims = _tier_dims(width, height, tilesize)
    tiers = [(math.ceil(dw / tilesize), math.ceil(dh / tilesize)) for dw, dh in dims]
    top = len(tiers) - 1
    cols, rows = tiers[top]
    before = sum(c * r for c, r in tiers[:top])  # tiles in all lower tiers

    def tilegroup(col: int, row: int) -> int:
        return (before + row * cols + col) // _GROUP_SIZE

    return top, cols, rows, tilegroup


def total_tiles(width: int, height: int, tilesize: int = 256) -> int:
    """Total tiles across all tiers (== NUMTILES); used for validation/tests."""
    dims = _tier_dims(width, height, tilesize)
    return sum(math.ceil(dw / tilesize) * math.ceil(dh / tilesize) for dw, dh in dims)


async def download_zoomify_image(
    session: aiohttp.ClientSession,
    tiles_base: str,
    out_path: Path,
    headers: dict | None = None,
    props: dict | None = None,
    concurrency: int = 8,
    quality: int = 90,
) -> bool:
    """Download every top-tier tile under *tiles_base* and stitch to *out_path*.

    *tiles_base* is the directory containing ImageProperties.xml and the
    TileGroup* folders. If *props* (width/height/tilesize) is not supplied it is
    fetched from {tiles_base}/ImageProperties.xml. Returns True on success.
    """
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Pillow is required for tiled (Zoomify) images: pip install Pillow"
        ) from e

    headers = headers or {}
    if props is None:
        async with session.get(f"{tiles_base}/ImageProperties.xml", headers=headers) as r:
            r.raise_for_status()
            props = parse_image_properties(await r.text())
        if not props:
            raise RuntimeError(f"Bad ImageProperties.xml at {tiles_base}")

    width, height, tilesize = props["width"], props["height"], props["tilesize"]
    top, cols, rows, tilegroup = zoomify_top_tier(width, height, tilesize)

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    sem = asyncio.Semaphore(concurrency)
    failed = 0

    async def fetch_tile(col: int, row: int):
        nonlocal failed
        url = f"{tiles_base}/TileGroup{tilegroup(col, row)}/{top}-{col}-{row}.jpg"
        async with sem:
            try:
                async with session.get(url, headers=headers) as r:
                    r.raise_for_status()
                    data = await r.read()
                return col, row, data
            except Exception as e:
                failed += 1
                logger.warning(f"[zoomify] tile {top}-{col}-{row} failed: {e}")
                return col, row, None

    results = await asyncio.gather(
        *[fetch_tile(c, r) for r in range(rows) for c in range(cols)]
    )
    for col, row, data in results:
        if not data:
            continue
        try:
            tile = Image.open(BytesIO(data))
            canvas.paste(tile, (col * tilesize, row * tilesize))
        except Exception as e:
            logger.warning(f"[zoomify] paste {top}-{col}-{row} failed: {e}")

    if failed > (cols * rows) // 2:
        logger.error(f"[zoomify] too many tile failures ({failed}); skip {out_path}")
        return False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=quality)
    return True
