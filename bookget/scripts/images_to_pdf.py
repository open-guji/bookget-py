#!/usr/bin/env python3
"""
images_to_pdf.py — assemble downloaded images into one or more PDFs.

By default, walks <input_dir>/images/, groups files by leading volume
prefix (e.g. "v01_*", "v02_*"), and writes <input_dir>/pdf/<book>_v<NN>.pdf
plus a combined <book>.pdf.

Files without a volume prefix are placed in a single PDF named after the
input directory.

Usage:
    python -m bookget.scripts.images_to_pdf <book_dir> [--single]
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List

from PIL import Image

# Force UTF-8 stdout/stderr on Windows so Japanese/CJK paths print cleanly.
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")


VOLUME_RE = re.compile(r"^v(\w+?)_(\d+)", re.IGNORECASE)


def collect_images(image_dir: Path) -> List[Path]:
    exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    files = [p for p in image_dir.iterdir() if p.suffix.lower() in exts]
    files.sort(key=_sort_key)
    return files


def _sort_key(p: Path):
    """Natural sort by (volume, page_number) when prefix matches; else by name."""
    m = VOLUME_RE.match(p.stem)
    if m:
        vol = m.group(1)
        try:
            page = int(m.group(2))
        except ValueError:
            page = 0
        return (0, vol, page, p.name)
    # Files like "0001.jpg"
    m2 = re.match(r"^(\d+)$", p.stem)
    if m2:
        return (1, "", int(m2.group(1)), p.name)
    return (2, "", 0, p.name)


def group_by_volume(files: List[Path]) -> Dict[str, List[Path]]:
    groups: Dict[str, List[Path]] = {}
    for p in files:
        m = VOLUME_RE.match(p.stem)
        vol = m.group(1) if m else ""
        groups.setdefault(vol, []).append(p)
    return groups


def write_pdf(images: List[Path], output: Path):
    """Write a single PDF from a list of image paths."""
    if not images:
        return
    output.parent.mkdir(parents=True, exist_ok=True)

    first, *rest = images
    with Image.open(first) as im:
        im_rgb = im.convert("RGB") if im.mode != "RGB" else im.copy()

    extras = []
    try:
        for p in rest:
            with Image.open(p) as im:
                extras.append(im.convert("RGB") if im.mode != "RGB" else im.copy())
        im_rgb.save(
            output,
            "PDF",
            save_all=True,
            append_images=extras,
            resolution=150.0,
        )
    finally:
        im_rgb.close()
        for im in extras:
            im.close()
    print(f"  wrote {output}  ({len(images)} pages)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("book_dir", type=Path,
                    help="Book directory (containing 'images/')")
    ap.add_argument("--single", action="store_true",
                    help="Write a single combined PDF, skip per-volume PDFs")
    ap.add_argument("--name", type=str, default=None,
                    help="Base name for output PDFs (default: directory name)")
    args = ap.parse_args()

    book_dir: Path = args.book_dir.resolve()
    image_dir = book_dir / "images"
    if not image_dir.is_dir():
        # Allow passing the images dir directly.
        if (book_dir / "v01_0001.jpg").exists() or any(book_dir.glob("*.jpg")):
            image_dir = book_dir
            book_dir = book_dir.parent
        else:
            print(f"error: {image_dir} not found", file=sys.stderr)
            sys.exit(1)

    files = collect_images(image_dir)
    if not files:
        print(f"error: no images in {image_dir}", file=sys.stderr)
        sys.exit(1)

    base_name = args.name or book_dir.name
    pdf_dir = book_dir / "pdf"

    print(f"Found {len(files)} images in {image_dir}")

    if args.single:
        write_pdf(files, pdf_dir / f"{base_name}.pdf")
        return

    groups = group_by_volume(files)
    has_volumes = bool([v for v in groups if v])

    if has_volumes:
        for vol in sorted(groups):
            if not vol:
                # Stray un-prefixed files: append to combined only.
                continue
            write_pdf(groups[vol], pdf_dir / f"{base_name}_v{vol}.pdf")
    # Always write a combined PDF as well.
    write_pdf(files, pdf_dir / f"{base_name}.pdf")


if __name__ == "__main__":
    main()
