# University of Tokyo, Institute for Advanced Studies on Asia
# 東京大学 東洋文化研究所 漢籍善本全文影像資料庫
# https://shanben.ioc.u-tokyo.ac.jp/

import re
from typing import List, Optional
from urllib.parse import quote, urlparse
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...logger import logger
from ...exceptions import MetadataExtractionError

_NU_RE = re.compile(r'nu=([A-Za-z0-9]+)')
_NO_RE = re.compile(r'no=(\d+)')
_PDF_RE = re.compile(r'href="pdf/([^"]+\.pdf)"', re.IGNORECASE)
_TITLE_RE = re.compile(r'<title>([^<]*)</title>', re.IGNORECASE)

_BASE = "https://shanben.ioc.u-tokyo.ac.jp"


@AdapterRegistry.register
class UTokyoShanbenAdapter(BaseSiteAdapter):
    """Adapter for 東大東洋文化研究所 漢籍善本全文影像資料庫.

    URL patterns:
    - List:  https://shanben.ioc.u-tokyo.ac.jp/list.php
    - Item:  https://shanben.ioc.u-tokyo.ac.jp/main_p.php?nu={nu}
             &order=rn_no&no={no}&tim=hb

    An item view is one fascicle (冊) and carries one whole-volume PDF:
        pdf/000772-十三經註疏崇禎中古虞毛氏汲古閣刊本-卷首.pdf

    Measured 2026-09-20:
    - `nu` alone identifies the record but the PDF link only appears on the
      full item view, so the caller's URL (with its `no=`) is what gets
      fetched — `list.php?nu=...` ignores the filter and returns the default
      listing, so the fascicle list cannot be looked up from `nu` alone.
    - Page images do exist, at `file/{nu}/{500|1200}/{冊}{頁}.jpg`, but the
      site publishes no index of them: finding them all means probing page
      numbers until a 404. The whole-volume PDF carries the same content in
      one request, so this adapter takes the PDF (as bookget's Go original
      does) and leaves per-page probing alone.
    - Records with nothing digitised beyond a cover (e.g. nu=A000500) have
      no PDF link at all; that is reported rather than returned as empty.
    """

    site_name = "東京大学東洋文化研究所 漢籍善本 (U-Tokyo)"
    site_id = "utokyo_shanben"
    site_domains = ["shanben.ioc.u-tokyo.ac.jp"]

    supports_iiif = False
    supports_images = False
    supports_pdf = True
    supports_text = False

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._source_urls: dict = {}

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        match = _NU_RE.search(url)
        if not match:
            raise MetadataExtractionError(
                f"東大漢籍地址里没有 nu 参数：{url}\n"
                f"（条目地址形如 main_p.php?nu=A000600&order=rn_no&no=00015&tim=hb）")
        nu = match.group(1)

        number = _NO_RE.search(url)
        book_id = f"{nu}_{number.group(1)}" if number else nu
        self._source_urls[book_id] = url
        return book_id

    def item_url(self, book_id: str) -> str:
        source = self._source_urls.get(book_id)
        if source:
            return source
        nu, _, number = book_id.partition("_")
        url = f"{_BASE}/main_p.php?nu={nu}&order=rn_no&tim=hb"
        return f"{url}&no={number}" if number else url

    async def _fetch_item_page(self, book_id: str) -> str:
        url = self.item_url(book_id)
        session = await self.get_session()
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                # The pages are Shift_JIS-era CGI output; let aiohttp guess
                # and fall back rather than hard-coding an encoding.
                return await response.text(errors="replace")
        except Exception as e:
            raise MetadataExtractionError(
                f"[utokyo_shanben] 取条目页失败：{url}（{e}）") from e

    @staticmethod
    def parse_item_page(html: str):
        """Return (title, [pdf paths]) from an item page."""
        title_match = _TITLE_RE.search(html)
        title = title_match.group(1).strip() if title_match else ""
        # The title uses an ideographic space between work and edition.
        title = title.replace("　", " ").strip()
        return title, _PDF_RE.findall(html)

    def pdf_url(self, path: str) -> str:
        # Filenames are Chinese, so they must be percent-encoded, but the
        # path separator must survive.
        return f"{_BASE}/pdf/{quote(path)}"

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        html = await self._fetch_item_page(book_id)
        title, pdfs = self.parse_item_page(html)

        metadata = BookMetadata(
            source_id=book_id,
            source_url=self.item_url(book_id),
            source_site=self.site_id,
            index_id=index_id,
        )
        metadata.title = title or f"U-Tokyo {book_id}"
        metadata.collection_unit = "東京大学東洋文化研究所"
        metadata.volume_info = pdfs[0].rsplit("-", 1)[-1][:-4] if pdfs else ""
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Return the fascicle PDF(s); this site publishes no page index."""
        html = await self._fetch_item_page(book_id)
        _, pdfs = self.parse_item_page(html)

        if not pdfs:
            raise MetadataExtractionError(
                f"[utokyo_shanben] 该条目没有可下载的 PDF："
                f"{self.item_url(book_id)}\n"
                f"（漢籍善本库里有些记录只数字化了书影封面，没有全文影像）")

        source_host = urlparse(self.item_url(book_id)).netloc or ""
        logger.info(f"U-Tokyo {book_id}: {len(pdfs)} PDF(s) on {source_host}")
        return [
            Resource(
                url=self.pdf_url(path),
                resource_type=ResourceType.PDF,
                order=index,
                page=str(index),
                filename=f"{book_id}_{index:02d}.pdf",
            )
            for index, path in enumerate(pdfs, start=1)
        ]
