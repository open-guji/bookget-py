# 國立故宮博物院 Open Data (National Palace Museum, Taipei)
# https://digitalarchive.npm.gov.tw/opendata/
#
# The NPM "Open Data" platform publishes 108,670 painting/calligraphy/antiquity
# records with CC BY 4.0 images (600萬像素 tier) and an IIIF Image API for the
# full-resolution files. Book-like objects (法書 calligraphy, 法帖 model-books,
# 拓片 rubbings, 繪畫 albums) live in the 書畫類 (dep=P) part of the site.
#
# NCL Taiwan rbook 適配器已搬到 other/ncl_rbook.py。

import asyncio
import html as _html
import json
import re
import ssl
from typing import Dict, List, Optional
from urllib.parse import quote

import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...models.search import SearchResponse, SearchResult
from ...exceptions import MetadataExtractionError


SITE = "https://digitalarchive.npm.gov.tw"
IIIF_IMAGE = "https://iiifod.npm.gov.tw/iiif/2"

# The site encodes a few rare characters as base + U+F6A4 (a private-use
# "compose" mark) + component, e.g. 木挈 for 㮮. Map the ones we know.
PUA_MAP = {"木挈": "㮮"}


def clean_html_text(s: str) -> str:
    """Strip tags, unescape entities (the site double-escapes some), collapse
    ASCII whitespace but keep U+3000 (the museum's titles use it)."""
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)      # line breaks must not glue words
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(_html.unescape(s)).replace("\xa0", " ")
    for k, v in PUA_MAP.items():
        s = s.replace(k, v)
    return re.sub(r"[ \t\r\n]+", " ", s).strip()


def parse_detail_page(page: str) -> Dict:
    """Parse an Open Data detail page (…/Pub/Detail?id=N&dep=P&mode=full).

    Returns a dict:
      title            品名 with the museum's original spacing
      fields           {label: value} from the key/value tables (基本資料 …)
      sections         {pane_id: {"title", "header", "rows", "note"}} — every
                       tab (基本資料 / 典藏尺寸 / 質地 / 題跋資料 / 印記資料 / 保存維護)
      image_names      IIIF image identifiers listed in the page gallery
      attribution      the museum's "複製標示文字" CC BY attribution string
    """
    body = re.sub(r"<!--.*?-->", "", page, flags=re.S)   # template leftovers live in comments
    tabs = dict(re.findall(
        r'data-bs-target="#(details-\d+)"[^>]*>\s*<span>(.*?)</span>', body, flags=re.S))
    sections: Dict[str, Dict] = {}
    panes = re.split(r'(?=<div class="tab-pane[^"]*" id="details-\d+")', body)[1:]
    for pane in panes:
        pid = re.match(r'<div class="tab-pane[^"]*" id="(details-\d+)"', pane).group(1)
        sec = {"title": clean_html_text(tabs.get(pid, pid)), "header": None, "rows": [], "note": None}
        note = re.search(r'<div class="nav-info">(.*?)</div>', pane, flags=re.S)
        if note:
            sec["note"] = clean_html_text(note.group(1))
        pane = re.sub(r'<a class="btn btn-more".*?</a>', "", pane, flags=re.S)   # "印記 expand_more" toggles
        # inscription rows may be followed by a collapsed <tr><td class="stamp-td"> holding a
        # nested table of that inscription's seals: fold those into the preceding row
        for block, tr in re.findall(
                r'(<tr>\s*<td[^>]*class="stamp-td">.*?</table>.*?</tr>)|(<tr>(?:(?!<tr>).)*?</tr>)',
                pane, flags=re.S):
            if block:
                inner = re.search(r"<table[^>]*>(.*?)</table>", block, flags=re.S)
                pairs = re.findall(r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>",
                                   inner.group(1) if inner else "", flags=re.S)
                pairs = [(clean_html_text(a), clean_html_text(b)) for a, b in pairs]
                if pairs and sec["rows"]:
                    sec["rows"][-1][-1] += "〔印記：" + "、".join(
                        f"{a}「{b}」" if a else f"「{b}」" for a, b in pairs) + "〕"
                continue
            ths = re.findall(r"<th[^>]*>(.*?)</th>", tr, flags=re.S)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
            if ths:
                sec["header"] = [clean_html_text(x) for x in ths]
            elif tds:
                sec["rows"].append([clean_html_text(x) for x in tds])
        sections[pid] = sec

    fields: Dict[str, str] = {}
    for sec in sections.values():
        if not sec["header"]:
            for row in sec["rows"]:
                if len(row) >= 2:
                    fields.setdefault(row[0], row[1])
    # the 文物統一編號 cell may also list every leaf's number; keep the first
    nums = re.findall(r"\S+?N\d{9}", fields.get("文物統一編號", ""))
    if nums:
        fields["文物統一編號"] = nums[0]
        if len(nums) > 1:
            fields["文物統一編號（其他）"] = "、".join(nums[1:])

    m = re.search(r'id="textToCopy">([^<]*)<', page)
    attribution = clean_html_text(m.group(1)) if m else ""
    title = attribution.split("。國立故宮博物院")[0] if "。國立故宮博物院" in attribution else ""
    if not title:
        m = re.search(r'<img alt="([^"]+)"[^>]*data-image-name=', page)
        title = clean_html_text(m.group(1)) if m else fields.get("品名", "")
    image_names = list(dict.fromkeys(re.findall(r'data-image-name="([A-Z0-9]+)"', page)))
    return {"title": title, "fields": fields, "sections": sections,
            "image_names": image_names, "attribution": attribution}


def parse_search_page(page: str) -> Dict:
    """Result cards of a POST /opendata/Pub/Search response.

    Returns {"items": [(id, dep, title)], "page_count": int}.
    """
    items = []
    for oid, dep, title in re.findall(
            r"onclick=\"Detail\('(\d+)', '([A-Z])'\)\".*?<div class=\"card-title\">(.*?)</div>", page, flags=re.S):
        items.append((oid, dep, clean_html_text(title)))
    m = re.search(r'"PageCount":(\d+)', page)
    return {"items": items, "page_count": int(m.group(1)) if m else 1}


def zh_title(title: str) -> str:
    """The Chinese title with normalised spaces and without the museum's English tail."""
    t = re.sub(r"\s+", " ", (title or "").replace("\u3000", " ")).strip()
    return re.sub(r"\s[\[(]?[A-Z][A-Za-z].*$", "", t).strip()


def work_title(title: str) -> str:
    """Album-level title: cut after the format word (冊/卷/軸 …) so leaf titles fall away,
    e.g. '宋榻大觀帖（九） 冊 晉王獻之吳興帖' -> '宋榻大觀帖（九） 冊'."""
    t = zh_title(title)
    m = re.search(r"^(.*?\s(?:冊頁|冊|卷|軸|單片|鏡片|橫披|成扇|屏))(\s|$)", t)
    return m.group(1) if m else t


def album_record(records: List[Dict]) -> Dict:
    """The album-level record: number ending N000000000 and the shortest 品名
    (leaf records append the leaf title to the album title)."""
    cands = [r for r in records if r["object_number"].endswith("N000000000")] or list(records)
    return min(cands, key=lambda r: (len(zh_title(r.get("title") or r["fields"].get("品名", ""))), int(r["id"])))


def work_canvases(records: List[Dict]):
    """[(label, record id)] for every image of a work, sorted by label; a leaf's images
    (label[9:19] == its number's N-part) map to that leaf record, others to the album record."""
    by_leaf = {}
    for r in records:
        if r["object_number"]:
            by_leaf.setdefault(r["object_number"][-10:], r["id"])
    for r in records:
        for n in r.get("object_numbers_more", []):       # a leaf spanning two images lists both
            by_leaf.setdefault(n[-10:], r["id"])
    labels = sorted({lab for r in records for lab in r["canvases"]})
    if not labels:
        return []
    album0 = album_record(records)["id"]
    return [(lab, by_leaf.get(lab[9:19], album0)) for lab in labels]


@AdapterRegistry.register
class PalaceMuseumTaipeiAdapter(BaseSiteAdapter):
    """
    國立故宮博物院 Open Data (National Palace Museum, Taipei).

    URL patterns (dep = department: P 書畫類, U 器物/織品類):
    - Detail:      https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=1528&dep=P&mode=full
                   https://digitalarchive.npm.gov.tw/opendata/Pub/Detail/1528?dep=P&mode=full
                   https://digitalarchive.npm.gov.tw/opendata/Pub/DetailEng/1528?dep=P
    - IIIF viewer: https://digitalarchive.npm.gov.tw/opendata/Integrate/IIIFViewer?id=1528&dep=P&imageName=
    - Collection:  https://digitalarchive.npm.gov.tw/Collection/Detail?id=11&dep=U

    Book id = dep + id, e.g. "P1528" (ids are numbered per department).
    Images: IIIF Image API 2 (level 2), full/full = native resolution
    (typically 3055×2291), licence CC BY 4.0 with the museum's attribution.
    """

    site_name = "臺灣故宮博物院 Open Data (NPM Taipei)"
    site_id = "npm_taipei"
    site_domains = ["digitalarchive.npm.gov.tw"]

    supports_iiif = True
    supports_search = True
    persist_raw_metadata = True     # full record (sections/seals/colophons) for the PDF sheet
    supports_text = False
    supports_images = True

    # Album mode (``bookget download --album``): treat the record as one leaf of a
    # work and download the whole album/scroll — every sibling record's images
    # and metadata, grouped by the image-identifier prefix (e.g. K2D000156).
    album_mode: bool = False
    # Also fetch the English detail page for bilingual labels on the PDF sheet.
    fetch_english: bool = True
    fetch_concurrency: int = 6

    def __init__(self, config=None):
        super().__init__(config)
        self._session = None
        self._detail_cache: Dict[str, Dict] = {}
        self._detail_en_cache: Dict[str, Dict] = {}
        self._record_cache: Dict[str, Dict] = {}
        self._work_cache: Dict[str, Dict] = {}

    # ------------------------------------------------------------------ http
    @staticmethod
    def _ssl_context():
        # iiifod.npm.gov.tw's certificate lacks a Subject Key Identifier, which
        # Python 3.13's default VERIFY_X509_STRICT rejects (curl accepts it).
        ctx = ssl.create_default_context()
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context())
            self._session = aiohttp.ClientSession(headers=self.get_headers(), connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get_text(self, url: str, retries: int = 4) -> str:
        session = await self.get_session()
        for attempt in range(retries):
            try:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.text()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    async def _post_json_text(self, url: str, payload: dict, retries: int = 4) -> str:
        session = await self.get_session()
        for attempt in range(retries):
            try:
                async with session.post(url, json=payload) as resp:
                    resp.raise_for_status()
                    return await resp.text()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    # ------------------------------------------------------------------ ids
    def extract_book_id(self, url: str) -> str:
        """'P1528' from any of the detail / viewer / collection URL forms."""
        m_id = re.search(r"[?&](?:id|cid)=(\d+)", url) or re.search(r"/Detail(?:Eng)?/(\d+)", url)
        m_dep = re.search(r"[?&]dep(?:t)?=([A-Za-z])", url)
        if not m_id:
            raise MetadataExtractionError(f"Could not extract NPM object id from URL: {url}")
        dep = (m_dep.group(1) if m_dep else "P").upper()
        return f"{dep}{m_id.group(1)}"

    @staticmethod
    def _split(book_id: str):
        m = re.fullmatch(r"([A-Z])(\d+)", book_id)
        if not m:
            raise MetadataExtractionError(f"Bad NPM book id: {book_id}")
        return m.group(1), m.group(2)

    def detail_url(self, book_id: str) -> str:
        dep, oid = self._split(book_id)
        return f"{SITE}/opendata/Pub/Detail?id={oid}&dep={dep}&mode=full"

    def manifest_url(self, book_id: str) -> str:
        dep, oid = self._split(book_id)
        return f"{SITE}/opendata/Integrate/GetJson?cid={oid}&dept={dep}&imageName="

    def detail_url_en(self, book_id: str) -> str:
        dep, oid = self._split(book_id)
        return f"{SITE}/opendata/Pub/DetailEng/{oid}?dep={dep}&mode=full"

    def viewer_url(self, book_id: str) -> str:
        dep, oid = self._split(book_id)
        return f"{SITE}/opendata/Integrate/IIIFViewer?id={oid}&dep={dep}&imageName="

    # ------------------------------------------------------------------ search
    SEARCH_PAGE_MAX = 500

    async def _search_page(self, query: str, page: int, size: int, dep: str = "P") -> Dict:
        """One page of the site's search. ``category:法帖`` (or ``分類:法帖``) filters by
        分類 (RegisterType); anything else is a keyword search (SearchContent), which
        also matches 文物統一編號 prefixes such as 故帖000156."""
        m = re.match(r"^(?:category|分類|cat)[:：]\s*(.+)$", query.strip())
        model = {"RegisterType": m.group(1).strip() if m else None, "IndexYear": None,
                 "WestBeginYear": 0, "WestEndYear": 0, "YearDisplay": "",
                 "SearchContent": None if m else query.strip(), "RegisterTypeEng": None,
                 "PageInfo": {"PageIndex": page, "PageSize": size, "PageCount": 1}}
        path = "/opendata/Pub/Search" if dep == "P" else "/opendata/Collection/Search"
        return parse_search_page(await self._post_json_text(f"{SITE}{path}", model))

    async def search(self, query: str, limit: int = 20, offset: int = 0) -> SearchResponse:
        size = max(1, min(limit or 20, self.SEARCH_PAGE_MAX))
        page = offset // size + 1
        res = await self._search_page(query, page, size)
        results = [SearchResult(title=t, page_id=int(oid), url=self.detail_url(f"{dep}{oid}"),
                                source_site=self.site_id, snippet=f"{dep}{oid}")
                   for oid, dep, t in res["items"]]
        has_more = page < res["page_count"]
        return SearchResponse(query=query, results=results, total_hits=0, has_more=has_more,
                              continuation=str(offset + len(results)) if has_more else "")

    async def search_all(self, query: str) -> List[SearchResult]:
        """Every result of a search (all pages), e.g. the whole 法帖 category."""
        out, page = [], 1
        while True:
            res = await self._search_page(query, page, self.SEARCH_PAGE_MAX)
            out += [SearchResult(title=t, page_id=int(oid), url=self.detail_url(f"{dep}{oid}"),
                                 source_site=self.site_id, snippet=f"{dep}{oid}")
                    for oid, dep, t in res["items"]]
            if page >= res["page_count"] or not res["items"]:
                return out
            page += 1

    # ------------------------------------------------------------------ metadata
    async def _detail(self, book_id: str) -> Dict:
        if book_id not in self._detail_cache:
            page = await self._get_text(self.detail_url(book_id))
            parsed = parse_detail_page(page)
            if not parsed["title"] and not parsed["fields"]:
                raise MetadataExtractionError(f"NPM detail page has no record: {book_id}")
            self._detail_cache[book_id] = parsed
        return self._detail_cache[book_id]

    async def _detail_en(self, book_id: str) -> Dict:
        """English detail page (labels for the bilingual sheet); {} when unavailable."""
        if book_id not in self._detail_en_cache:
            try:
                self._detail_en_cache[book_id] = parse_detail_page(await self._get_text(self.detail_url_en(book_id)))
            except Exception:
                self._detail_en_cache[book_id] = {}
        return self._detail_en_cache[book_id]

    async def _record(self, book_id: str) -> Dict:
        """One Open Data record as a plain dict (the schema the PDF builder and the
        work grouping use): id, dep, title, fields, sections, canvases, object_number …"""
        if book_id in self._record_cache:
            return self._record_cache[book_id]
        dep, oid = self._split(book_id)
        d = await self._detail(book_id)
        names = []
        try:
            manifest = await self.get_iiif_manifest(book_id)
        except MetadataExtractionError:
            manifest = None
        if manifest and manifest.get("sequences"):
            names = [c["label"] for c in manifest["sequences"][0].get("canvases", [])]
        canvases = sorted(set(names) | set(d["image_names"]))
        num = d["fields"].get("文物統一編號", "")
        more = [x for x in re.split(r"[、,\s]+", d["fields"].get("文物統一編號（其他）", "")) if x]
        rec = {"id": oid, "dep": dep, "book_id": book_id, "title": d["title"] or d["fields"].get("品名", ""),
               "fields": d["fields"], "sections": d["sections"], "canvases": canvases,
               "object_number": num, "object_numbers_more": more, "attribution": d["attribution"],
               "manifest_label": (manifest or {}).get("label", ""), "detail_url": self.detail_url(book_id)}
        self._record_cache[book_id] = rec
        return rec

    @staticmethod
    def work_key(record: Dict) -> str:
        """Image-identifier prefix shared by every image of a work, e.g. K2D000156."""
        keys = sorted({lab[:9] for lab in record["canvases"]})
        return keys[0] if keys else ""

    async def _work(self, book_id: str) -> Dict:
        """All records of the work (album/scroll) this record belongs to.

        Siblings are found by searching the site for the accession prefix
        (故帖000156 matches every 故帖000156N0000000xx leaf) and kept when their
        images share the record's identifier prefix (K2D000156)."""
        rec = await self._record(book_id)
        key = self.work_key(rec)
        cache_key = key or book_id
        if cache_key in self._work_cache:
            return self._work_cache[cache_key]
        prefix = rec["object_number"][:-10] if re.search(r"N\d{9}$", rec["object_number"]) else ""
        records = [rec]
        if prefix and key:
            hits = await self.search_all(prefix)
            ids = [f"{rec['dep']}{h.page_id}" for h in hits if h.snippet.startswith(rec["dep"])]
            sem = asyncio.Semaphore(self.fetch_concurrency)

            async def fetch(bid):
                async with sem:
                    try:
                        return await self._record(bid)
                    except Exception:
                        return None
            for r in await asyncio.gather(*(fetch(b) for b in ids if b != book_id)):
                if r and (self.work_key(r) == key or (not r["canvases"] and r["object_number"].startswith(prefix))):
                    records.append(r)
        records.sort(key=lambda r: (r["object_number"], int(r["id"])))
        album = album_record(records)
        work = {"key": key, "prefix": prefix or key, "album_id": album["book_id"],
                "album_title": work_title(album["title"]), "records": records,
                "canvases": work_canvases(records)}
        self._work_cache[cache_key] = work
        return work

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        if self.album_mode:
            return await self._work_metadata(book_id, index_id)
        d = await self._detail(book_id)
        f = d["fields"]
        md = BookMetadata(source_id=book_id, source_url=self.detail_url(book_id),
                          source_site=self.site_id, index_id=index_id)
        md.title = d["title"] or f.get("品名", "")
        for name in re.split(r"[、;；]", f.get("作者", "")):
            name = name.strip()
            if name:
                zh, _, en = name.partition(",")
                md.creators.append(Creator(name=zh.strip() or name, role=en.strip()))
        md.dynasty = (re.match(r"^(民國|清|明|元|宋|北宋|南宋|唐|晉|五代|遼|金|隋|漢|三國|北魏|魏)", md.title) or [None, ""])[1]
        md.date = f.get("創作時間", "")
        md.category = f.get("分類", "")
        md.doc_type = f.get("書體", "")
        md.language = f.get("作品語文", "")
        md.volume_info = f.get("數量", "")
        md.call_number = f.get("文物統一編號", "")
        md.collection_unit = "國立故宮博物院"
        md.license = "CC BY 4.0"
        md.rights = d["attribution"] or f"{md.title}。國立故宮博物院，台北，CC BY 4.0 @ www.npm.gov.tw"
        md.iiif_manifest_url = self.manifest_url(book_id)
        sec = d["sections"]
        dims = [f"{r[0]} {r[1]}" for r in sec.get("details-2", {}).get("rows", []) if len(r) >= 2]
        md.dimensions = "；".join(dims)
        if f.get("釋文"):
            md.notes.append("釋文：" + f["釋文"])
        for r in sec.get("details-4", {}).get("rows", []):        # 題跋
            if len(r) >= 6:
                md.provenance.append(f"{r[0]}（{r[1] or '—'}，{r[2]}，{r[4]}）：{r[5] or r[3]}")
        for r in sec.get("details-5", {}).get("rows", []):        # 印記
            if len(r) >= 3:
                md.provenance.append(f"{r[0]}（{r[1]}）：{r[2]}" if r[1] else f"{r[0]}：{r[2]}")
        md.raw_metadata = {
            "kind": "record",
            "fields": f,
            "sections": sec,
            "sections_en": (await self._detail_en(book_id)).get("sections", {}) if self.fetch_english else {},
            "image_names": d["image_names"],
            "attribution": d["attribution"],
            "detail_url": self.detail_url(book_id),
            "detail_url_en": self.detail_url_en(book_id),
            "viewer_url": self.viewer_url(book_id),
            "manifest_url": self.manifest_url(book_id),
        }
        return md

    async def _work_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Album-mode metadata: one BookMetadata for the whole work."""
        w = await self._work(book_id)
        album = album_record(w["records"])
        af = album["fields"]
        md = BookMetadata(source_id=w["prefix"] or book_id, source_url=album["detail_url"],
                          source_site=self.site_id, index_id=index_id)
        md.title = w["album_title"]
        seen = set()
        for r in w["records"]:
            for name in re.split(r"[、;；]", r["fields"].get("作者", "")):
                name = name.strip()
                zh, _, en = name.partition(",")
                if zh.strip() and zh.strip() not in seen:
                    seen.add(zh.strip())
                    md.creators.append(Creator(name=zh.strip(), role=en.strip()))
        md.dynasty = (re.match(r"^(民國|清|明|元|宋|北宋|南宋|唐|晉|五代|遼|金|隋|漢|三國|北魏|魏)", md.title) or [None, ""])[1]
        md.date = af.get("創作時間", "")
        md.category = af.get("分類", "")
        md.doc_type = af.get("書體", "")
        md.language = af.get("作品語文", "")
        md.volume_info = f"{len(w['records'])} 筆記錄 / {len(w['canvases'])} 幅"
        md.volumes = len(w["records"])
        md.pages = len(w["canvases"])
        md.call_number = w["prefix"]
        md.collection_unit = "國立故宮博物院"
        md.license = "CC BY 4.0"
        md.rights = f"{md.title}。國立故宮博物院，台北，CC BY 4.0 @ www.npm.gov.tw"
        md.iiif_manifest_url = self.manifest_url(album["book_id"])
        for r in w["records"]:
            if r["fields"].get("釋文"):
                md.notes.append(f"{r['object_number'] or r['book_id']} 釋文：{r['fields']['釋文']}")
        md.raw_metadata = {
            "kind": "work", "key": w["key"], "prefix": w["prefix"], "album_id": w["album_id"],
            "album_detail_url": album["detail_url"], "album_manifest_url": self.manifest_url(album["book_id"]),
            "canvases": [list(c) for c in w["canvases"]],
            "records": w["records"],
        }
        return md

    # ------------------------------------------------------------------ images
    async def get_iiif_manifest(self, book_id: str) -> Optional[dict]:
        text = await self._get_text(self.manifest_url(book_id))
        if not text.strip():            # GetJson returns an empty body for some records
            return None
        try:
            return json.loads(text)
        except ValueError:
            raise MetadataExtractionError(f"NPM manifest is not JSON for {book_id}: {text[:80]!r}")

    @staticmethod
    def image_service(name: str) -> str:
        """IIIF Image service id for an image identifier such as C2B000007N000000000PAL."""
        return f"{IIIF_IMAGE}/{quote(name[:3])}%2F{quote(name)}"

    async def get_image_list(self, book_id: str) -> List[Resource]:
        if self.album_mode:
            w = await self._work(book_id)
            by_id = {r["id"]: r for r in w["records"]}
            resources = []
            for i, (name, rid) in enumerate(w["canvases"], 1):
                service = self.image_service(name)
                resources.append(Resource(
                    url=f"{service}/full/full/0/default.jpg", resource_type=ResourceType.IMAGE,
                    order=i, page=name, volume=by_id[rid]["object_number"],
                    filename=f"{i:03d}_{name}.jpg", iiif_service_id=service))
            return resources
        names: List[str] = []
        manifest = await self.get_iiif_manifest(book_id)
        if manifest and manifest.get("sequences"):
            for canvas in manifest["sequences"][0].get("canvases", []):
                names.append(canvas["label"])
        if not names:
            # the detail page's gallery lists the same identifiers
            names = list((await self._detail(book_id))["image_names"])
        names = sorted(dict.fromkeys(names))
        resources = []
        for i, name in enumerate(names, 1):
            service = self.image_service(name)
            resources.append(Resource(
                url=f"{service}/full/full/0/default.jpg",
                resource_type=ResourceType.IMAGE,
                order=i,
                page=name,
                filename=f"{i:03d}_{name}.jpg",
                iiif_service_id=service,
            ))
        return resources
