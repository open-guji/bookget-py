# 臺灣華文電子書庫 (Taiwan eBook, NCL) Adapter
# https://taiwanebook.ncl.edu.tw/
#
# 臺灣國家圖書館 1911–1949 年間出版書籍數位化平台。非 IIIF：每書一個（或多個）
# PDF，經 PDF.js 閱讀。流程（對齊 bookget app/huawen.go）：
#   1. 詳情頁 /zh-tw/book/{id} → 書名在麵包屑 <div class="active section">…</div>
#   2. 閱讀頁 /zh-tw/book/{id}/reader → HTML 內含 viewer.html?file={pdfPath}
#   3. PDF：https://taiwanebook.ncl.edu.tw{pdfPath}（單冊一般為 /ebkFiles/{id}/{id}.PDF）
# PDF 檔本身可直接 GET（200 application/pdf），頁面上的 reCAPTCHA 不擋檔案下載。

import re
import ssl
from pathlib import Path
from typing import Callable, List, Optional

import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...models.manifest import ManifestNode, NodeStatus
from ...logger import logger
from ...exceptions import MetadataExtractionError

_VIEWER_FILE_RE = re.compile(r'viewer\.html\?file=([^"\'&\s]+\.PDF)', re.IGNORECASE)
_PDF_PATH_RE = re.compile(r'(/ebkFiles/[^"\'\s]+\.PDF)', re.IGNORECASE)
_ACTIVE_SECTION_RE = re.compile(
    r'<div[^>]*class="active section"[^>]*>([^<]+)</div>', re.IGNORECASE)


@AdapterRegistry.register
class TaiwanEbookAdapter(BaseSiteAdapter):
    """Adapter for 臺灣華文電子書庫 (taiwanebook.ncl.edu.tw) — PDF download."""

    site_name = "臺灣華文電子書庫"
    site_id = "taiwan_ebook"
    site_domains = ["taiwanebook.ncl.edu.tw"]

    supports_iiif = False
    supports_images = True   # so discover_structure builds a downloadable node
    supports_pdf = True
    supports_text = False

    BASE = "https://taiwanebook.ncl.edu.tw"
    default_headers = {"Referer": "https://taiwanebook.ncl.edu.tw/"}

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        """NCL's TLS cert is missing the Subject Key Identifier extension, which
        Python 3.13+ strict X.509 verification rejects (browsers accept it).
        Keep chain verification but drop the over-strict flag."""
        ctx = ssl.create_default_context()
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context())
            self._session = aiohttp.ClientSession(
                headers=self.get_headers(), connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        m = re.search(r'/book/([^/?#]+)', url)
        if m:
            return m.group(1)
        raise MetadataExtractionError(
            f"Could not extract Taiwan eBook id from URL: {url}")

    async def _fetch(self, url: str) -> str:
        session = await self.get_session()
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.text(errors="ignore")

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        html = await self._fetch(f"{self.BASE}/zh-tw/book/{book_id}")
        meta = BookMetadata(
            source_id=book_id,
            source_url=f"{self.BASE}/zh-tw/book/{book_id}",
            source_site=self.site_id,
            index_id=index_id,
            collection_unit="國家圖書館 (臺灣)",
        )
        # Title lives in the breadcrumb's active section
        matches = [m.strip() for m in _ACTIVE_SECTION_RE.findall(html) if m.strip()]
        if matches:
            meta.title = matches[-1]
        return meta

    async def _get_pdf_paths(self, book_id: str) -> List[str]:
        """Scrape PDF path(s) from the reader page; fall back to the derived path."""
        html = await self._fetch(f"{self.BASE}/zh-tw/book/{book_id}/reader")
        paths = list(dict.fromkeys(
            _VIEWER_FILE_RE.findall(html) + _PDF_PATH_RE.findall(html)))
        if not paths:
            paths = [f"/ebkFiles/{book_id}/{book_id}.PDF"]
        return paths

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Return the book's PDF file(s) as downloadable resources."""
        paths = await self._get_pdf_paths(book_id)
        resources: List[Resource] = []
        multi = len(paths) > 1
        for i, path in enumerate(paths, 1):
            url = path if path.startswith("http") else f"{self.BASE}{path}"
            fname = f"{book_id}_{i:02d}.pdf" if multi else f"{book_id}.pdf"
            resources.append(Resource(
                url=url,
                resource_type=ResourceType.PDF,
                order=i,
                filename=fname,
            ))
        logger.info(f"[taiwan_ebook] {book_id}: {len(resources)} PDF(s)")
        return resources

    async def get_pdf_url(self, book_id: str) -> Optional[str]:
        paths = await self._get_pdf_paths(book_id)
        p = paths[0]
        return p if p.startswith("http") else f"{self.BASE}{p}"

    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """Stream each PDF to disk (PDFs can be large)."""
        images = node.source_data.get("images")
        if not images:
            urls = node.source_data.get("image_urls", [])
            images = [{"url": u, "filename": f"{book_id}_{i + 1:02d}.pdf"}
                      for i, u in enumerate(urls)]
        if not images:
            logger.warning(f"[taiwan_ebook] node {node.id} has no PDFs")
            node.status = NodeStatus.FAILED
            return node

        node.status = NodeStatus.DOWNLOADING
        node.total_items = len(images)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        session = await self.get_session()
        headers = self.get_headers()
        downloaded = 0

        for item in images:
            url = item["url"]
            filename = item.get("filename") or url.rsplit("/", 1)[-1]
            dest = output_dir / filename
            if dest.exists() and dest.stat().st_size > 1024:
                downloaded += 1
                if progress_callback:
                    progress_callback(downloaded, len(images))
                continue
            try:
                async with session.get(url, headers=headers) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            f.write(chunk)
                downloaded += 1
                if progress_callback:
                    progress_callback(downloaded, len(images))
            except Exception as e:
                logger.warning(f"[taiwan_ebook] failed {url}: {e}")
                if dest.exists():
                    dest.unlink()

        node.downloaded_items = downloaded
        node.failed_items = len(images) - downloaded
        node.status = (NodeStatus.COMPLETED if downloaded == len(images)
                       else NodeStatus.FAILED)
        return node
