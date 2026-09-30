"""A small PDF writer that embeds JPEG files without re-encoding.

Why not Pillow's PDF save: it re-encodes every image (quality loss, no
metadata beyond a title). This writer keeps the JPEG bytes verbatim
(DCTDecode) and adds what an archival scan needs: Info dictionary with
custom keys, an XMP packet (Dublin Core + xmpRights), outlines (bookmarks),
page labels and embedded file attachments. Output is PDF 1.7, uncompressed
object structure (the images dominate the size anyway).
"""

from __future__ import annotations

import datetime as _dt
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as _xml


def jpeg_size(data: bytes) -> Tuple[int, int, int]:
    """(width, height, components) from the SOF marker; raises ValueError if not a JPEG."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG (no SOI marker)")
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            raise ValueError("bad JPEG marker structure")
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h, data[i + 9]
        i += 2 + seglen
    raise ValueError("no SOF marker found")


def pdf_text(s: str) -> bytes:
    """PDF text string (UTF-16BE with BOM, hex encoded): safe for any Unicode."""
    return b"<FEFF" + s.encode("utf-16-be").hex().upper().encode() + b">"


def pdf_literal(s: str) -> bytes:
    """PDF literal string: plain ASCII when possible, else UTF-16BE with BOM.
    (Some readers show hex strings raw in page labels, so labels use this form.)"""
    raw = s.encode("ascii") if s.isascii() else b"\xfe\xff" + s.encode("utf-16-be")
    esc = raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").replace(b"\r", b"\\r").replace(b"\n", b"\\n")
    return b"(" + esc + b")"


def pdf_name_safe(s: str) -> bytes:
    """A PDF name (/Key) for custom Info keys: ASCII letters/digits only."""
    return b"/" + "".join(ch for ch in s if ch.isalnum()).encode("ascii", "ignore")


@dataclass
class Outline:
    level: int
    title: str
    page: int          # 0-based page index


@dataclass
class Attachment:
    name: str
    data: bytes
    mime: str = "application/octet-stream"
    description: str = ""


@dataclass
class PdfWriter:
    """Collect pages and metadata, then write() the file."""
    dpi: float = 300.0
    info: Dict[str, str] = field(default_factory=dict)      # Title/Author/Subject/Keywords/Creator + custom keys
    xmp: Dict[str, object] = field(default_factory=dict)     # see _xmp_packet for supported keys
    outlines: List[Outline] = field(default_factory=list)
    attachments: List[Attachment] = field(default_factory=list)
    _pages: List[dict] = field(default_factory=list)         # {"jpeg", "w", "h", "cs", "label", "pw", "ph"}

    # ------------------------------------------------------------------ pages
    def add_jpeg(self, data: bytes, label: Optional[str] = None, dpi: Optional[float] = None) -> int:
        """Append a page holding the JPEG at native pixel size (page size = px / dpi)."""
        w, h, comps = jpeg_size(data)
        cs = {1: b"/DeviceGray", 3: b"/DeviceRGB", 4: b"/DeviceCMYK"}[comps]
        d = dpi or self.dpi
        self._pages.append({"jpeg": data, "w": w, "h": h, "cs": cs, "label": label,
                            "pw": w * 72.0 / d, "ph": h * 72.0 / d, "decode": comps == 4})
        return len(self._pages) - 1

    @property
    def page_count(self) -> int:
        return len(self._pages)

    # ------------------------------------------------------------------ helpers
    def _xmp_packet(self) -> bytes:
        x = self.xmp
        now = _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")

        def lang_alt(tag, value):
            return f"<{tag}><rdf:Alt><rdf:li xml:lang=\"x-default\">{_xml(str(value))}</rdf:li></rdf:Alt></{tag}>" if value else ""

        def seq(tag, values, kind="Seq"):
            return (f"<{tag}><rdf:{kind}>" + "".join(f"<rdf:li>{_xml(str(v))}</rdf:li>" for v in values) + f"</rdf:{kind}></{tag}>") if values else ""

        def simple(tag, value):
            return f"<{tag}>{_xml(str(value))}</{tag}>" if value else ""

        body = "".join([
            lang_alt("dc:title", x.get("title")),
            seq("dc:creator", x.get("creators", [])),
            lang_alt("dc:description", x.get("description")),
            seq("dc:subject", x.get("keywords", []), "Bag"),
            lang_alt("dc:rights", x.get("rights")),
            seq("dc:publisher", [x["publisher"]] if x.get("publisher") else [], "Bag"),
            simple("dc:source", x.get("source")),
            seq("dc:type", [x.get("type", "Image")], "Bag"),
            seq("dc:language", [x.get("language", "zh-TW")], "Bag"),
            simple("dc:identifier", x.get("identifier")),
            simple("xmpRights:WebStatement", x.get("license_url")),
            simple("xmpRights:Marked", "True" if x.get("rights") else ""),
            simple("xmp:CreateDate", now),
            simple("xmp:CreatorTool", x.get("creator_tool", "bookget")),
            simple("pdf:Producer", x.get("producer", "bookget PdfWriter")),
            simple("pdf:Keywords", ", ".join(x.get("keywords", []))),
        ])
        pkt = ('<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
               '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
               '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
               'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:pdf="http://ns.adobe.com/pdf/1.3/" '
               'xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/">'
               + body + '</rdf:Description></rdf:RDF></x:xmpmeta>' + " " * 200 + '<?xpacket end="w"?>')
        return pkt.encode("utf-8")

    @staticmethod
    def _page_label_tree(labels: Sequence[Optional[str]]) -> bytes:
        """/PageLabels number tree: one range per page (explicit labels), roman numerals for
        pages whose label is None (used for the metadata sheet at the end)."""
        nums = []
        roman_start = None
        for i, lab in enumerate(labels):
            if lab is None:
                if roman_start is None:
                    roman_start = i
                    nums.append(b"%d << /S /r >>" % i)
            else:
                roman_start = None
                nums.append(b"%d << /P %s >>" % (i, pdf_literal(lab)))
        return b"<< /Nums [ " + b" ".join(nums) + b" ] >>"

    # ------------------------------------------------------------------ write
    def write(self, path) -> None:
        if not self._pages:
            raise ValueError("no pages")
        objs: List[bytes] = []

        def add(body: bytes) -> int:
            objs.append(body)
            return len(objs)

        def stream(dict_body: bytes, data: bytes) -> bytes:
            return dict_body + b" /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"

        catalog_n = add(b"")   # 1
        pages_n = add(b"")     # 2
        page_ids = []
        for p in self._pages:
            extra = b" /Decode [1 0 1 0 1 0 1 0]" if p["decode"] else b""     # Adobe-style inverted CMYK JPEGs
            img = add(stream(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode%s"
                             % (p["w"], p["h"], p["cs"], extra), p["jpeg"]))
            content = b"q %.4f 0 0 %.4f 0 0 cm /Im0 Do Q" % (p["pw"], p["ph"])
            cont = add(stream(b"<<", content))
            page = add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.4f %.4f] /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
                       % (pages_n, p["pw"], p["ph"], img, cont))
            page_ids.append(page)
        objs[pages_n - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % i for i in page_ids), len(page_ids))

        # outlines (two levels are enough for volume/leaf bookmarks)
        outlines_n = None
        if self.outlines:
            outlines_n = add(b"")
            items = []      # (obj number placeholder index, outline)
            for o in self.outlines:
                items.append([add(b""), o])
            # link siblings/children
            def kids(level, start, end):
                res = []
                i = start
                while i < end:
                    if items[i][1].level == level:
                        j = i + 1
                        while j < end and items[j][1].level > level:
                            j += 1
                        res.append((i, j))
                        i = j
                    else:
                        i += 1
                return res
            def build(level, start, end, parent_n):
                groups = kids(level, start, end)
                first = last = None
                for gi, (i, j) in enumerate(groups):
                    n, o = items[i]
                    prev_n = items[groups[gi - 1][0]][0] if gi > 0 else None
                    next_n = items[groups[gi + 1][0]][0] if gi + 1 < len(groups) else None
                    cfirst, clast, ccount = build(level + 1, i + 1, j, n)
                    body = b"<< /Title %s /Parent %d 0 R /Dest [%d 0 R /XYZ 0 %.2f null]" % (
                        pdf_text(o.title), parent_n, page_ids[o.page], self._pages[o.page]["ph"])
                    if prev_n:
                        body += b" /Prev %d 0 R" % prev_n
                    if next_n:
                        body += b" /Next %d 0 R" % next_n
                    if cfirst:
                        body += b" /First %d 0 R /Last %d 0 R /Count %d" % (cfirst, clast, ccount)
                    body += b" >>"
                    objs[n - 1] = body
                    if first is None:
                        first = n
                    last = n
                return first, last, len(groups)
            first, last, count = build(0, 0, len(items), outlines_n)
            objs[outlines_n - 1] = b"<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (first, last, count)

        # attachments
        names_n = None
        if self.attachments:
            specs = []
            for a in self.attachments:
                subtype = b"/" + a.mime.replace("/", "#2F").encode("ascii", "ignore")
                ef = add(stream(b"<< /Type /EmbeddedFile /Subtype %s /Params << /Size %d >>" % (subtype, len(a.data)), a.data))
                fs = add(b"<< /Type /Filespec /F %s /UF %s /Desc %s /EF << /F %d 0 R /UF %d 0 R >> >>" % (
                    pdf_text(a.name), pdf_text(a.name), pdf_text(a.description), ef, ef))
                specs.append((a.name, fs))
            specs.sort()
            names_n = add(b"<< /Names [ " + b" ".join(b"%s %d 0 R" % (pdf_text(n), fs) for n, fs in specs) + b" ] >>")

        meta_n = add(stream(b"<< /Type /Metadata /Subtype /XML", self._xmp_packet()))
        labels_n = add(self._page_label_tree([p["label"] for p in self._pages]))
        catalog = b"<< /Type /Catalog /Pages %d 0 R /Metadata %d 0 R /PageLabels %d 0 R" % (pages_n, meta_n, labels_n)
        if outlines_n:
            catalog += b" /Outlines %d 0 R /PageMode /UseOutlines" % outlines_n
        if names_n:
            catalog += b" /Names << /EmbeddedFiles %d 0 R >>" % names_n
        catalog += b" >>"
        objs[catalog_n - 1] = catalog

        info = dict(self.info)
        info.setdefault("Producer", "bookget PdfWriter")
        info.setdefault("CreationDate", _dt.datetime.now().strftime("D:%Y%m%d%H%M%S"))
        info_body = b"<<" + b"".join(b" %s %s" % (pdf_name_safe(k), (b"(" + v.encode() + b")") if k == "CreationDate" else pdf_text(str(v)))
                                       for k, v in info.items() if v) + b" >>"
        info_n = add(info_body)

        out = bytearray(b"%PDF-1.7\n%\xE2\xE3\xCF\xD3\n")
        offsets = []
        for n, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for o in offsets:
            out += b"%010d 00000 n \n" % o
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog_n, info_n, xref)
        with open(path, "wb") as f:
            f.write(out)
