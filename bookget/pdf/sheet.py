"""Render a metadata sheet (文物資料表-style form) to JPEG page images with Pillow.

The sheet is a sequence of sections; each section is either a label/value
form or a table. Text is laid out character by character so CJK wraps
correctly. A CJK-capable font is required: set BOOKGET_CJK_FONT or rely on
the common system locations probed by find_cjk_font(). Without a font the
caller skips the sheet (the PDF still carries all metadata in Info/XMP and
the attached JSON).
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

FONT_CANDIDATES = [
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/source-han-serif/SourceHanSerifTC-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Windows
    "C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/msjhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/mingliu.ttc", "C:/Windows/Fonts/simsun.ttc",
]


def find_cjk_font() -> Optional[str]:
    """First existing CJK font: $BOOKGET_CJK_FONT, then common system paths, then TeX Live's Source Han."""
    env = os.environ.get("BOOKGET_CJK_FONT")
    if env and Path(env).exists():
        return env
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    for root in (Path.home() / "texmf", Path.home() / "texlive", Path("/usr/share/texlive"), Path("/usr/local/texlive")):
        if root.exists():
            for pat in ("**/SourceHanSerif*-Regular.otf", "**/SourceHanSans*-Regular.otf", "**/FandolSong-Regular.otf"):
                for hit in root.glob(pat):
                    return str(hit)
    return None


@dataclass
class Section:
    title: str
    title_en: str = ""
    fields: List[Tuple[str, str]] = field(default_factory=list)      # label/value form
    header: List[str] = field(default_factory=list)                   # or a table
    rows: List[List[str]] = field(default_factory=list)
    note: str = ""


@dataclass
class SheetSpec:
    heading: str                      # e.g. 國立故宮博物院　文物資料表
    subheading: str = ""              # e.g. National Palace Museum, Taipei · Open Data P1528
    sections: List[Section] = field(default_factory=list)


class _Layout:
    """A4 at `dpi`, simple boxed-form layout."""

    def __init__(self, font_path: str, dpi: int = 200):
        from PIL import ImageFont
        self.dpi = dpi
        self.W, self.H = int(8.27 * dpi), int(11.69 * dpi)
        self.margin = int(0.7 * dpi)
        self.font = ImageFont.truetype(font_path, int(dpi * 0.15))
        self.small = ImageFont.truetype(font_path, int(dpi * 0.115))
        self.big = ImageFont.truetype(font_path, int(dpi * 0.24))
        self.line = int(dpi * 0.21)
        self.pad = int(dpi * 0.04)
        self.label_w = int(2.0 * dpi)
        self.pages: List[object] = []          # PIL.Image.Image per page
        self._new_page()

    def _new_page(self):
        from PIL import Image, ImageDraw
        self.img = Image.new("RGB", (self.W, self.H), "white")
        self.draw = ImageDraw.Draw(self.img)
        self.y = self.margin
        self.pages.append(self.img)

    def _ensure(self, height: int):
        if self.y + height > self.H - self.margin:
            self._new_page()

    def wrap(self, text: str, width: int, font) -> List[str]:
        """Character-level wrapping (CJK has no word boundaries)."""
        lines, cur = [], ""
        for ch in text.replace("\n", " "):
            if self.draw.textlength(cur + ch, font=font) > width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur or not lines:
            lines.append(cur)
        return lines

    def heading(self, text: str, sub: str = ""):
        w = self.draw.textlength(text, font=self.big)
        self.draw.text(((self.W - w) / 2, self.y), text, font=self.big, fill="black")
        self.y += int(self.line * 1.6)
        if sub:
            w = self.draw.textlength(sub, font=self.small)
            self.draw.text(((self.W - w) / 2, self.y), sub, font=self.small, fill="#555555")
            self.y += self.line
        self.y += self.line // 2

    def bar(self, title: str, en: str = ""):
        self._ensure(self.line * 3)
        x0, x1 = self.margin, self.W - self.margin
        self.draw.rectangle([x0, self.y, x1, self.y + self.line + self.pad], fill="#3a3a3a")
        self.draw.text((x0 + self.pad, self.y + self.pad // 2), title + ("   " + en if en else ""), font=self.font, fill="white")
        self.y += self.line + self.pad

    def form_row(self, label: str, value: str):
        x0, x1 = self.margin, self.W - self.margin
        vx = x0 + self.label_w
        lines = self.wrap(value, x1 - vx - 2 * self.pad, self.font) or [""]
        labs = self.wrap(label, self.label_w - 2 * self.pad, self.small)
        h = max(len(lines) * self.line, len(labs) * self.line) + 2 * self.pad
        if h > self.H - 2 * self.margin - self.line:     # a value longer than a page: split it
            chunk = max(1, (self.H - 2 * self.margin - 3 * self.line) // self.line)
            for k in range(0, len(lines), chunk):
                self.form_row(label if k == 0 else "（續）", "".join(lines[k:k + chunk]))
            return
        self._ensure(h)
        self.draw.rectangle([x0, self.y, vx, self.y + h], fill="#ebebeb", outline="#8c8c8c")
        self.draw.rectangle([vx, self.y, x1, self.y + h], outline="#8c8c8c")
        for i, l in enumerate(labs):
            self.draw.text((x0 + self.pad, self.y + self.pad + i * self.line), l, font=self.small, fill="#333333")
        for i, l in enumerate(lines):
            self.draw.text((vx + self.pad, self.y + self.pad + i * self.line), l, font=self.font, fill="black")
        self.y += h

    def table(self, header: Sequence[str], rows: Sequence[Sequence[str]]):
        x0, x1 = self.margin, self.W - self.margin
        n = max(1, len(header))
        colw = (x1 - x0) // n
        def row(cells, fill=None, font=None):
            font = font or self.font
            wrapped = [self.wrap(str(c), colw - 2 * self.pad, font) for c in cells]
            h = max(len(w) for w in wrapped) * self.line + 2 * self.pad
            self._ensure(h)
            for i, w in enumerate(wrapped):
                cx = x0 + i * colw
                self.draw.rectangle([cx, self.y, cx + colw, self.y + h], fill=fill, outline="#8c8c8c")
                for j, l in enumerate(w):
                    self.draw.text((cx + self.pad, self.y + self.pad + j * self.line), l, font=font, fill="black")
            self.y += h
        row(header, fill="#ebebeb", font=self.small)
        for r in rows:
            cells = list(r)[:n] + [""] * (n - len(r))
            row(cells)

    def gap(self):
        self.y += self.line // 2


def render_sheet(spec: SheetSpec, font_path: Optional[str] = None, dpi: int = 200, quality: int = 90) -> List[bytes]:
    """Render the sheet; returns JPEG bytes per page. Raises RuntimeError if no CJK font."""
    font_path = font_path or find_cjk_font()
    if not font_path:
        raise RuntimeError("no CJK font found; set BOOKGET_CJK_FONT to a .ttf/.otf/.ttc file")
    lay = _Layout(font_path, dpi)
    lay.heading(spec.heading, spec.subheading)
    for s in spec.sections:
        lay.bar(s.title, s.title_en)
        if s.note:
            lay.form_row("", s.note)
        for label, value in s.fields:
            lay.form_row(label, value)
        if s.header:
            lay.table(s.header, s.rows)
        lay.gap()
    out = []
    for img in lay.pages:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, dpi=(dpi, dpi))
        out.append(buf.getvalue())
    return out
