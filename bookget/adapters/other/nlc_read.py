# 中國國家圖書館·讀者雲門戶（read.nlc.cn）適配器
#
# 與 nlc_guji.py（guji.nlc.cn 新版「中華古籍智慧化服務平台」）是兩套獨立站點，
# 接口完全不同。讀者雲門戶提供 PDF 下載入口，需走 token chain：
#   1. GET 詳情頁或閱讀器頁，HTML 含 <iframe ... tokenKey="..." timeKey="..." timeFlag="...">
#   2. GET /menhu/OutOpenBook/getReaderNew?aid=&bid=&kime=<timeKey>&fime=<timeFlag>
#      header 必須帶 myreader: <tokenKey> + Referer: WebPDFJRWorker.js
#
# 支持的 URL：
#   - 詳情頁：http://read.nlc.cn/allSearch/searchDetail?searchType=...&fid=<fid>
#   - 閱讀器：http://read.nlc.cn/OutOpenBook/OpenObjectBook?aid=<aid>&bid=<bid>
#
# 邏輯改寫自 deweizhu/bookget Go 版 (app/nlc.go) ChinaNlc 結構體。

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...exceptions import MetadataExtractionError
from ...logger import logger
from ...models.book import BookMetadata, Creator, Resource, ResourceType
from ...models.manifest import ManifestNode, NodeStatus, ResourceKind


@AdapterRegistry.register
class NLCReadAdapter(BaseSiteAdapter):
    """中國國家圖書館讀者雲門戶 read.nlc.cn 適配器（PDF 單文件下載）。"""

    site_name = "中國國家圖書館·讀者雲門戶"
    site_id = "nlc_read"
    site_domains = ["read.nlc.cn"]

    supports_iiif = False
    supports_text = False
    supports_images = False
    supports_pdf = True

    BASE = "http://read.nlc.cn"
    PDF_REFERER = "http://read.nlc.cn/static/webpdf/lib/WebPDFJRWorker.js"

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        # detail 頁拿到後緩存：book_id -> {'aid', 'bid', 'title', 'detail_html'}
        self._detail_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # URL routing
    # ------------------------------------------------------------------
    @classmethod
    def can_handle(cls, url: str) -> bool:
        return "read.nlc.cn" in url.lower()

    def extract_book_id(self, url: str) -> str:
        """讀者雲門戶有兩種入口：

        - 詳情頁 ?fid=<num>           → book_id = "fid:<num>"
        - 閱讀器 ?aid=<a>&bid=<b>     → book_id = "aid:<a>/bid:<b>"

        統一在 book_id 裡保存原始參數以便後續調用。
        """
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "fid" in qs:
            return f"fid:{qs['fid'][0]}"
        if "aid" in qs and "bid" in qs:
            return f"aid:{qs['aid'][0]}/bid:{qs['bid'][0]}"
        raise MetadataExtractionError(
            f"無法從 URL 提取 read.nlc.cn book_id: {url}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _fetch_text(self, url: str, referer: str = None) -> str:
        session = await self.get_session()
        headers = {"Referer": referer} if referer else None
        async with session.get(url, headers=headers) as r:
            r.raise_for_status()
            return await r.text(errors="ignore")

    async def _resolve_aid_bid(self, book_id: str) -> tuple[str, str, str]:
        """從 book_id 解析出 (aid, bid, detail_url)。

        - book_id == "fid:X" → GET 詳情頁，從 HTML 取 "openObjectBook?aid=&bid="
          或 indexName / identifier 推 aid（indexName=data_<aid>）。
        - book_id == "aid:X/bid:Y" → 直接拆解。
        """
        if book_id.startswith("aid:"):
            m = re.match(r"aid:([^/]+)/bid:(.+)", book_id)
            if not m:
                raise MetadataExtractionError(f"book_id 格式錯誤: {book_id}")
            aid, bid = m.group(1), m.group(2)
            detail_url = (
                f"{self.BASE}/OutOpenBook/OpenObjectBook?aid={aid}&bid={bid}"
            )
            return aid, bid, detail_url

        if not book_id.startswith("fid:"):
            raise MetadataExtractionError(f"未知 book_id 形態: {book_id}")

        fid = book_id[4:]
        # 用 data_892 作占位 indexName；服務端會根據 fid 查到實際資源
        # 對 SBGJ（善本古籍）類，indexName 通常是 data_892
        index_name = "data_892"
        detail_url = (
            f"{self.BASE}/allSearch/searchDetail?"
            f"searchType=1002&showType=1&indexName={index_name}&fid={fid}"
        )
        html = await self._fetch_text(detail_url)

        # 從 detail HTML 抓 OpenObjectBook?aid=<a>&bid=<b>
        m = re.search(
            r"OpenObjectBook\?aid=([^&'\"]+)&bid=([^'\"]+)", html
        )
        if not m:
            raise MetadataExtractionError(
                f"詳情頁未含 OpenObjectBook 鏈接，可能非 PDF 類資源: {detail_url}"
            )
        aid, bid = m.group(1), m.group(2)
        title_m = re.search(r"var\s+title\s*=\s*'([^']+)'", html)
        title = title_m.group(1) if title_m else ""
        self._detail_cache[book_id] = {
            "aid": aid, "bid": bid, "title": title, "detail_html": html,
        }
        return aid, bid, detail_url

    async def _get_token(self, aid: str, bid: str) -> tuple[str, str, str]:
        """從 OpenObjectBook 頁面 HTML 取 (tokenKey, timeKey, timeFlag)。

        每次調用都重取，token 有時效。
        """
        url = f"{self.BASE}/OutOpenBook/OpenObjectBook?aid={aid}&bid={bid}"
        html = await self._fetch_text(url)
        out = {"tokenKey": "", "timeKey": "", "timeFlag": ""}
        for m in re.finditer(
            r'(tokenKey|timeKey|timeFlag)="([a-zA-Z0-9]+)"', html
        ):
            out[m.group(1)] = m.group(2)
        if not all(out.values()):
            raise MetadataExtractionError(
                f"未能從 OpenObjectBook 取到 token chain: aid={aid} bid={bid}"
            )
        return out["tokenKey"], out["timeKey"], out["timeFlag"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        aid, bid, detail_url = await self._resolve_aid_bid(book_id)
        cache = self._detail_cache.get(book_id, {})
        title = cache.get("title", "")
        if not title:
            html = cache.get("detail_html") or await self._fetch_text(detail_url)
            tm = re.search(r"var\s+title\s*=\s*'([^']+)'", html)
            if tm:
                title = tm.group(1)
        md = BookMetadata(
            source_id=book_id,
            source_url=detail_url,
            source_site=self.site_id,
            index_id=index_id,
            title=title,
        )
        md.collection_unit = "中國國家圖書館"
        md.raw_metadata = {"aid": aid, "bid": bid}
        return md

    async def get_image_list(self, book_id: str) -> List[Resource]:
        """讀者雲門戶按 PDF 提供，這裡返回一個 PDF Resource 占位。

        URL 是 OpenObjectBook 入口頁（含 aid+bid，可識別），實際下載走
        download_node()，會臨時取 token 再拼 getReaderNew 並挂 myreader header。
        """
        aid, bid, detail_url = await self._resolve_aid_bid(book_id)
        identifier = f"aid{aid}_bid{bid}".replace(".", "_")
        return [
            Resource(
                url=detail_url,
                resource_type=ResourceType.PDF,
                order=1,
                filename=f"{identifier}.pdf",
            )
        ]

    async def get_pdf_url(self, book_id: str) -> Optional[str]:
        """返回 OpenObjectBook 入口頁 URL（含 aid+bid）。

        注意：這不是直接可 GET 的 PDF URL—實際下載必須走 token chain。
        若需要可下載 URL，建議用 discover_structure() + download_node()，
        或調用 _build_pdf_url()。
        """
        aid, bid, detail_url = await self._resolve_aid_bid(book_id)
        return detail_url

    async def _build_pdf_url(self, aid: str, bid: str) -> tuple[str, dict[str, str]]:
        """生成當前可用的 PDF 下載 URL + 必需的 headers。

        返回的 token 約幾分鐘內有效，過期需重新調用本方法。
        """
        token_key, time_key, time_flag = await self._get_token(aid, bid)
        pdf_url = (
            f"{self.BASE}/menhu/OutOpenBook/getReaderNew?"
            f"aid={aid}&bid={bid}&kime={time_key}&fime={time_flag}"
        )
        headers = {
            "myreader": token_key,
            "Referer": self.PDF_REFERER,
        }
        return pdf_url, headers

    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
    ) -> ManifestNode:
        """下載 PDF 到 output_dir。

        節點是 _discover_from_legacy 構造的單 image node（占位）。我們忽略其
        URL，重新從 aid/bid 取 token + 拼 getReaderNew + 下載。
        """
        aid, bid, _ = await self._resolve_aid_bid(book_id)
        identifier = f"aid{aid}_bid{bid}".replace(".", "_")
        node.status = NodeStatus.DOWNLOADING

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        dest = output_dir / f"{identifier}.pdf"

        pdf_url, headers = await self._build_pdf_url(aid, bid)
        session = await self.get_session()
        try:
            async with session.get(pdf_url, headers=headers) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                if total == 0:
                    raise MetadataExtractionError(
                        f"PDF 響應 Content-Length=0，token 可能失效: {pdf_url}"
                    )
                downloaded = 0
                with open(dest, "wb") as f:
                    async for chunk in r.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
            node.status = NodeStatus.COMPLETED
            node.downloaded_items = 1
            node.total_items = 1
            node.local_path = str(dest)
            logger.info(
                f"[nlc_read] downloaded {identifier}.pdf ({downloaded:,} bytes)"
            )
        except Exception as e:
            logger.error(f"[nlc_read] download failed: {e}")
            node.status = NodeStatus.FAILED
            node.failed_items = 1
        return node
