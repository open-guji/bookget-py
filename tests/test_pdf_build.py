"""Tests for bookget.pdf: writer, schema, both engines (no network)."""

import io
import json
import re

import pytest

from bookget.pdf.writer import Attachment, Outline, PdfWriter, jpeg_size, pdf_literal, pdf_text
from bookget.pdf.schema import document_schema, file_stem, zh_title
from bookget.pdf.build import build_book_pdf, pdf_filename, sheet_spec
from bookget.pdf.latex import chunks, esc, find_lualatex, hs, render_tex

PIL = pytest.importorskip("PIL.Image", reason="Pillow needed to make test JPEGs")


def _jpeg(w=40, h=30, color=(200, 100, 50)):
    buf = io.BytesIO()
    PIL.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


class TestWriter:
    def test_jpeg_size(self):
        assert jpeg_size(_jpeg(40, 30))[:2] == (40, 30)
        with pytest.raises(ValueError):
            jpeg_size(b"\x89PNG....")

    def test_strings(self):
        assert pdf_text("A") == b"<FEFF0041>"
        assert pdf_literal("ab(c)") == b"(ab\\(c\\))"
        assert pdf_literal("冊").startswith(b"(\xfe\xff")

    def test_write_structure(self, tmp_path):
        w = PdfWriter(dpi=300, info={"Title": "測試　冊", "Author": "王羲之", "ObjectNumber": "故帖000001"},
                      xmp={"title": "測試　冊", "creators": ["王羲之"], "keywords": ["k1"], "rights": "CC BY"})
        p0 = w.add_jpeg(_jpeg(), label="IMG_A")
        p1 = w.add_jpeg(_jpeg(60, 20), label=None)
        w.outlines += [Outline(0, "第一", p0), Outline(1, "子", p0), Outline(0, "表", p1)]
        w.attachments.append(Attachment("metadata.json", b"{}", "application/json", "d"))
        out = tmp_path / "t.pdf"
        w.write(out)
        data = out.read_bytes()
        assert data.startswith(b"%PDF-1.7") and data.rstrip().endswith(b"%%EOF")
        assert data.count(b"/Type /Page ") == 2
        assert b"/Filter /DCTDecode" in data and _jpeg() in data      # embedded verbatim
        assert b"/MediaBox [0 0 9.6000 7.2000]" in data              # 40px @300dpi
        assert b"/Outlines" in data and data.count(b"/Title <FEFF") == 4   # 3 bookmarks + Info /Title
        assert b"/EmbeddedFiles" in data and b"/Subtype /application#2Fjson" in data
        assert b"/PageLabels" in data and b"(IMG_A)" in data and b"/S /r" in data
        assert b"dc:title" in data and b"xmpRights" in data
        assert b"/ObjectNumber <FEFF" in data
        xref_pos = int(re.search(rb"startxref\n(\d+)", data).group(1))
        assert data[xref_pos:xref_pos + 4] == b"xref"
        first = int(re.search(rb"\n(\d{10}) 00000 n", data).group(1))
        assert data[first:first + 7] == b"1 0 obj"

    def test_empty_raises(self, tmp_path):
        with pytest.raises(ValueError):
            PdfWriter().write(tmp_path / "x.pdf")


class TestNaming:
    def test_zh_title_drops_english_tail(self):
        assert zh_title("清紀昀欽定四庫全書簡明目錄（經部）　卷 Catalogue of the Siku") == "清紀昀欽定四庫全書簡明目錄（經部） 卷"

    def test_album_suffix_dropped_leaf_kept(self):
        assert file_stem({"title": "北宋搨絳帖（六）　冊", "call_number": "故帖000047N000000000"}, "NPM") == "NPM-故帖000047_北宋搨絳帖_六_冊"
        assert file_stem({"title": "宋榻大觀帖（九）　冊　晉王獻之吳興帖", "call_number": "故帖000156N000000012"}, "NPM") == \
            "NPM-故帖000156N000000012_宋榻大觀帖_九_冊_晉王獻之吳興帖"
        assert file_stem({"title": "宋榻大觀帖（九） 冊", "call_number": "故帖000156"}, "NPM") == "NPM-故帖000156_宋榻大觀帖_九_冊"

    def test_pdf_filename_without_number(self):
        assert pdf_filename({"title": "a/b: c", "source_id": "X1"}, "") == "X1_a_b_c.pdf"


# ---------------------------------------------------------------- fixtures for book dirs
def _record(oid, num, more, canvases, title, seals=None, text=""):
    sections = {"details-1": {"title": "基本資料", "header": None, "note": None,
                              "rows": [["文物統一編號", num], ["品名", title], ["分類", "法帖"], ["作者", "王獻之,Wang Xianzhi"], ["書體", "行草書"]]},
                "details-3": {"title": "質地", "header": ["質地位置", "質地"], "rows": [["本幅", "紙"]], "note": None}}
    if seals:
        sections["details-5"] = {"title": "印記資料", "header": ["印記類別", "印主", "印記"], "rows": seals, "note": None}
    fields = {"文物統一編號": num, "品名": title, "分類": "法帖", "作者": "王獻之,Wang Xianzhi", "書體": "行草書"}
    if text:
        fields["釋文"] = text
    if more:
        fields["文物統一編號（其他）"] = "、".join(more)
    return {"id": oid, "dep": "P", "book_id": f"P{oid}", "title": title, "fields": fields, "sections": sections,
            "canvases": canvases, "object_number": num, "object_numbers_more": more, "attribution": "",
            "manifest_label": "", "detail_url": f"https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id={oid}&dep=P&mode=full"}


def work_dir(tmp_path):
    d = tmp_path / "album"
    (d / "images").mkdir(parents=True)
    recs = [_record("1", "故帖000156N000000001", [], ["K2D000156N000000001PAA"], "宋榻大觀帖（九）　冊　晉王獻之相過帖",
                    text="吾十一日發吳興。" * 90),
            _record("2", "故帖000156N000000001", ["故帖000156N000000002"], ["K2D000156N000000001PAA", "K2D000156N000000002PAA"],
                    "宋榻大觀帖（九）　冊　晉王獻之諸女帖", seals=[["作者印記", "王獻之", "逸少"]])]
    md = {"source_id": "故帖000156", "source_site": "npm_taipei", "source_url": recs[0]["detail_url"],
          "title": "宋榻大觀帖（九） 冊", "creators": [{"name": "王獻之", "role": "Wang Xianzhi", "dynasty": ""}],
          "dynasty": "宋", "category": "法帖", "doc_type": "行草書", "call_number": "故帖000156",
          "collection_unit": "國立故宮博物院", "license": "CC BY 4.0", "rights": "attr", "notes": [], "provenance": []}
    raw = {"kind": "work", "key": "K2D000156", "prefix": "故帖000156", "album_id": "P1",
           "album_detail_url": recs[0]["detail_url"], "album_manifest_url": "https://x/manifest",
           "canvases": [["K2D000156N000000001PAA", "1"], ["K2D000156N000000002PAA", "2"]], "records": recs}
    (d / "metadata.json").write_text(json.dumps(md, ensure_ascii=False), encoding="utf-8")
    (d / "raw.npm_taipei.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    for i, lab in enumerate(["K2D000156N000000001PAA", "K2D000156N000000002PAA"], 1):
        (d / "images" / f"{i:03d}_{lab}.jpg").write_bytes(_jpeg(50 + i, 40))
    return d


def record_dir(tmp_path):
    d = tmp_path / "P16797"
    (d / "images").mkdir(parents=True)
    r = _record("16797", "故帖000156N000000012", ["故帖000156N000000013"], ["K2D000156N000000012PAA", "K2D000156N000000013PAA"],
                "宋榻大觀帖（九）　冊　晉王獻之吳興帖", text="吾十一日發吳興")
    md = {"source_id": "P16797", "source_site": "npm_taipei", "source_url": r["detail_url"], "title": r["title"],
          "creators": [{"name": "王獻之", "role": "Wang Xianzhi", "dynasty": ""}], "category": "法帖",
          "call_number": r["object_number"], "collection_unit": "國立故宮博物院", "license": "CC BY 4.0", "rights": "attr"}
    raw = {"kind": "record", "fields": r["fields"], "sections": r["sections"],
           "sections_en": {"details-1": {"title": "Details", "header": None, "rows": [["Object Number", "x"], ["Title", "y"]]}},
           "image_names": r["canvases"], "attribution": "宋榻大觀帖（九）　冊　晉王獻之吳興帖。國立故宮博物院，台北，CC BY 4.0 @ www.npm.gov.tw",
           "detail_url": r["detail_url"], "detail_url_en": "https://x/en", "viewer_url": "https://x/v", "manifest_url": "https://x/m"}
    (d / "metadata.json").write_text(json.dumps(md, ensure_ascii=False), encoding="utf-8")
    (d / "raw.npm_taipei.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    for i, lab in enumerate(r["canvases"], 1):
        (d / "images" / f"{i:03d}_{lab}.jpg").write_bytes(_jpeg(60 + i, 40))     # distinct bytes per page
    return d


def generic_dir(tmp_path):
    d = tmp_path / "G1"
    (d / "images").mkdir(parents=True)
    md = {"source_id": "G1", "source_site": "harvard", "source_url": "https://h/1", "title": "周易 十卷",
          "creators": [{"name": "王弼", "role": "注", "dynasty": "魏"}], "call_number": "T 1234", "license": "", "rights": ""}
    (d / "metadata.json").write_text(json.dumps(md, ensure_ascii=False), encoding="utf-8")
    (d / "images" / "0001.jpg").write_bytes(_jpeg())
    return d


class TestSchema:
    def test_work_schema(self, tmp_path):
        m = document_schema(work_dir(tmp_path))
        assert m["source_system"] == "npm-opendata-work"
        assert m["file_stem"] == "NPM-故帖000156_宋榻大觀帖_九_冊"
        assert m["title_field"] == "作品" and m["record_label"].endswith("2 筆記錄")
        ids = [s["id"] for s in m["sections"]]
        assert ids[:2] == ["basic", "details-3"] and "leaves" in ids and "trans" in ids and "details-5-all" in ids
        # image 2 is owned by record 2 through its "other" number
        assert m["pages"][1]["extra"] == "故帖000156N000000001" and m["pages"][1]["record_id"] == "2"
        assert m["pages"][0]["bookmarks"][0][1].startswith("故帖000156N000000001")
        assert m["pdfinfo"]["OpenDataIDs"] == "P1, P2"
        assert m["license"]["attribution_zh"].startswith("宋榻大觀帖（九） 冊。國立故宮博物院")

    def test_record_schema(self, tmp_path):
        m = document_schema(record_dir(tmp_path))
        assert m["source_system"] == "npm-opendata"
        assert m["file_stem"] == "NPM-故帖000156N000000012_宋榻大觀帖_九_冊_晉王獻之吳興帖"
        basic = m["sections"][0]
        assert basic["fields"][0] == {"label_zh": "文物統一編號", "label_en": "Object Number", "value": "故帖000156N000000012"}
        assert basic["fields"][-1]["label_zh"] == "文物統一編號（其他）"
        assert m["pdfinfo"]["ObjectNumber"] == "故帖000156N000000012"
        assert m["urls"]["detail_en"] == "https://x/en"

    def test_generic_schema(self, tmp_path):
        m = document_schema(generic_dir(tmp_path))
        assert m["file_stem"] == "HARVARD-T_1234_周易_十卷"
        assert m["sections"][0]["fields"][1]["value"] == "王弼（注）"
        assert m["license"]["image_license"] == ""

    def test_reverse_and_prefix(self, tmp_path):
        m = document_schema(work_dir(tmp_path), reverse=True, name_prefix="X")
        assert m["pages"][0]["image_name"].endswith("002PAA") and m["file_stem"].startswith("X-")


class TestLatexSource:
    def test_helpers(self):
        assert esc("a_b&c 木挈 -- ") == r"a\_b\&c 㮮 -{}- "
        assert hs("a{b}_c") == r"ab\textunderscore{}c"
        assert chunks("甲。" * 5, 6) == ["甲。甲。甲。", "甲。甲。"]
        assert chunks("x" * 10, 4) == ["xxxx", "xxxx", "xx"]

    def test_render_tex(self, tmp_path):
        d = work_dir(tmp_path)
        m = document_schema(d)
        tex = render_tex(m, d, {"cjk": "C.otf", "latin": "L.otf", "mono": "M.otf"}, 300.0)
        assert tex.startswith(r"\documentclass") and tex.rstrip().endswith(r"\end{document}")
        assert r"\setmainjfont{C.otf}" in tex
        assert tex.count(r"\imagepage{") == 2 and r"\thispdfpagelabel" in tex
        assert r"pdftitle={宋榻大觀帖（九） 冊}" in tex and "ObjectNumberPrefix={故帖000156}" in tex
        assert r"\embedfile[filespec=metadata.json" in tex and "raw.npm_taipei.json" in tex
        assert r"\begin{form}{基本資料（總記錄）}{Details of the album record}" in tex
        assert r"\sbar{4}{開頁記錄}{Leaf records}" in tex
        assert r"\begin{form}{授權與引用}" in tex and r"\url{https://creativecommons.org/licenses/by/4.0/}" in tex
        assert r"\url{https://github.com/open-guji/bookget-py}" in tex
        # a long 釋文 becomes continuation rows inside the breakable table, never a bare row > page
        assert tex.count(r"\val{吾十一日發吳興。") >= 2


class TestBuild:
    def test_native_without_sheet(self, tmp_path):
        d = work_dir(tmp_path)
        out = build_book_pdf(d, sheet=False, verify=False)
        assert out == d / "pdf" / "NPM-故帖000156_宋榻大觀帖_九_冊.pdf"
        data = out.read_bytes()
        assert data.count(b"/Type /Page ") == 2
        assert b"(K2D000156N000000001PAA)" in data
        assert data.count(b"/Type /EmbeddedFile ") == 2
        assert b"/ObjectNumberPrefix <FEFF" in data and b"/OpenDataIDs <FEFF" in data

    def test_native_reverse_and_output(self, tmp_path):
        d = work_dir(tmp_path)
        out = build_book_pdf(d, tmp_path / "o.pdf", sheet=False, reverse=True, verify=False)
        data = out.read_bytes()
        assert data.index(b"(K2D000156N000000002PAA)") < data.index(b"(K2D000156N000000001PAA)")

    def test_native_sheet_spec(self, tmp_path):
        m = document_schema(work_dir(tmp_path))
        spec = sheet_spec(m)
        titles = [s.title for s in spec.sections]
        assert titles[0] == "基本資料（總記錄）" and "授權與引用" in titles and titles[-1] == "來源與製作"
        assert spec.heading.startswith("國立故宮博物院")

    def test_native_with_sheet_if_font(self, tmp_path):
        from bookget.pdf.sheet import find_cjk_font
        if not find_cjk_font():
            pytest.skip("no CJK font on this machine")
        out = build_book_pdf(work_dir(tmp_path), sheet=True, sheet_dpi=72, verify=False)
        data = out.read_bytes()
        assert data.count(b"/Type /Page ") >= 3 and b"/S /r" in data

    def test_verify_if_pymupdf(self, tmp_path):
        pytest.importorskip("pymupdf")
        from bookget.pdf.sheet import find_cjk_font
        d = record_dir(tmp_path)
        out = build_book_pdf(d, sheet=bool(find_cjk_font()), sheet_dpi=72, verify=True)   # sheet pages tolerated
        assert out.exists()
        from bookget.pdf.verify import verify_pdf
        files = sorted((d / "images").iterdir())
        assert verify_pdf(out, files)[0]
        ok, msg, _, _ = verify_pdf(out, files[::-1])          # wrong order → byte mismatch
        assert not ok and "differs" in msg
        ok, msg, _, _ = verify_pdf(out, files + files)        # more content pages than embedded
        assert not ok                                        # count or byte mismatch, depending on sheet pages

    def test_bad_engine(self, tmp_path):
        with pytest.raises(ValueError):
            build_book_pdf(work_dir(tmp_path), engine="pdflatex")

    def test_missing_images(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(FileNotFoundError):
            build_book_pdf(tmp_path / "empty", sheet=False)

    @pytest.mark.skipif(not find_lualatex(), reason="no LuaLaTeX")
    def test_latex_engine(self, tmp_path):
        d = work_dir(tmp_path)
        out = build_book_pdf(d, engine="latex", verify=False, keep_build=True)
        assert out.name == "NPM-故帖000156_宋榻大觀帖_九_冊.pdf" and out.stat().st_size > 1000
        assert (d / "build" / "doc.log").exists()
        pymupdf = pytest.importorskip("pymupdf")
        doc = pymupdf.open(str(out))
        assert doc.page_count >= 3 and doc.metadata["title"] == "宋榻大觀帖（九） 冊"
        assert [pg.get_images()[0][2] for pg in list(doc)[:2]] == [51, 52]
        assert doc.embfile_names() == ["metadata.json", "raw.npm_taipei.json"]
        assert doc.get_toc()[0][1].startswith("故帖000156N000000001")
