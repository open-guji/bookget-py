# 臺灣國家圖書館「古籍與特藏文獻資源」rbook.ncl.edu.tw 適配器
#
# 反爬要點（詳見 D:/workspace/overview/.claude/skills/fetch-ncl-rbook/SKILL.md）：
#   - 滑塊拼圖驗證碼 — 必須人工過（headed Playwright）
#   - imageControl.js 動態注入 getImageKey()（3-rail fence 加密），輸入字串每次頁面加載不同，無法在 Python 端複刻
#   - /Watermark/getToken POST 每次返回 "imgToken:nextKey"，下次 POST 的字段名 = getImageKey()(prev_nextKey)
#   - 單 token 可拉 ~80-150 張；同 (token, page) 組合只能成功一次
#   - IP rate limit：並發 >1 或速率 >1 張/秒 → 429，冷卻 5 分鐘以上
#
# 策略：把全部 token / 限速 / 重試邏輯放在瀏覽器 JS 內（fire-and-forget 循環），
# Python 端定期 poll window.NCL.dlState 與 blobs，把已成功的 blob 取回寫盤。
# 這套 JS 等價於 scripts/fetch-ncl-rbook/{prep,download}.js 的內聯版。

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse, parse_qs

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...exceptions import DownloadError, MetadataExtractionError
from ...logger import logger
from ...models.book import BookMetadata, Creator, Resource, ResourceType
from ...models.manifest import ManifestNode, NodeStatus

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# 瀏覽器端 prep + download 循環。在 Playwright 頁面上下文中跑。
# 必須在 viewer 頁（含 #ImageDisplay + getImageKey）已過 captcha 後執行。
# 跑完 _NCL_PREP_JS 後 window.NCL 就緒；_NCL_DL_JS 啟動 fire-and-forget 循環。
_NCL_PREP_JS = r"""
async () => {
  if (!document.getElementById('ImageDisplay') || typeof getImageKey !== 'function') {
    return { err: 'not viewer page or imageControl.js missing' };
  }
  const $ = window.jQuery;
  if (!$) return { err: 'jQuery missing' };

  const md = {
    title: document.getElementById('Title_Main')?.value || '',
    bookno: document.getElementById('Identifier_BookNo')?.value || '',
    accession: document.getElementById('Identifier_Accession')?.value || '',
    call_number: document.getElementById('Identifier_CallNumber')?.value || '',
    source: document.getElementById('Source_Source')?.value || '',
    rights_owner: document.getElementById('Rights_Owner')?.value || '',
    rights_owner_country: document.getElementById('Rights_OwnerCountry')?.value || '',
    url: location.href,
  };

  const bases = [...document.querySelectorAll('.ImageC a[pageno]')].map(a => ({
    pageno: parseInt(a.getAttribute('pageno'), 10),
    href: a.href,
  }));
  if (!bases.length) return { err: 'no .ImageC found' };

  // 劫持 XHR 抓 getToken response（imageControl.js 主動發起）
  const log = [];
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__nclUrl = u; return origOpen.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    if (this.__nclUrl && this.__nclUrl.indexOf('Watermark/getToken') >= 0) {
      this.addEventListener('load', () => { try { log.push(this.responseText); } catch (e) {} });
    }
    return origSend.apply(this, arguments);
  };

  // 觸發 changePage(5) 讓 imageControl.js 自己發一次 POST，劫持到 response
  $('#sel-content-no').val(5).trigger('change');
  const dl = Date.now() + 8000;
  while (!log.length && Date.now() < dl) await new Promise(r => setTimeout(r, 100));
  if (!log.length) return { err: 'no getToken xhr captured' };

  const parsed = JSON.parse(log[log.length - 1]);
  const [, nextKey1] = (parsed.token || '').split(':');

  // 用 nextKey1 算字段名，手動再 POST 一次拿 fresh token（沒被消耗過）
  const fn = getImageKey();
  const field = fn(nextKey1);
  const rvt = document.querySelector('input[name="__RequestVerificationToken"]').value;
  const body = encodeURIComponent(field) + '=' + encodeURIComponent(rvt);
  const r = await fetch('/NCLSearch/Watermark/getToken', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
    body
  });
  const j = await r.json();
  const [freshToken, nextKey2] = j.token.split(':');
  if (!freshToken) return { err: 'no fresh token', resp: j };

  window.NCL = {
    md, bases, token: freshToken, next_key: nextKey2,
    rvt, captured_at: Date.now(), consumed_pages: [5],
    blobs: new Array(bases.length),
  };
  return { ok: true, md, bases };
}
"""

# fire-and-forget 下載循環。接受 {skip: number[]} 參數（已寫盤的 page 不再下）。
# 進度寫到 window.NCL.dlState。
_NCL_DL_JS = r"""
(args) => {
  if (!window.NCL || !window.NCL.token) return { err: 'run prep first' };
  if (window.NCL.dlState?.running) return { err: 'already running' };
  const NCL = window.NCL;
  NCL.dlState = {
    running: true, stop: false, start: Date.now(),
    done: 0, ok: 0, fail: 0, refresh: 0, refresh_fail: 0,
    consec_fail: 0, last_429: 0, last_keepalive: 0, fatal: null,
    gen: (NCL.dlState?.gen || 0) + 1,
  };
  const ST = NCL.dlState;
  const myGen = ST.gen;
  const fn = getImageKey();
  const skipSet = new Set(args?.skip || []);
  // 加固參數
  const MAX_CONSEC_FAIL = 10;     // 連續失敗 N 張 → fatal stop（避免雪崩）
  const REFRESH_RETRY = 5;        // refresh 失敗最多重試（5xx 可能是 server 抖動）
  const REFRESH_RETRY_MS = 8000;  // 基礎重試間隔；5xx 會用指數退避
  const KEEPALIVE_EVERY = 200;    // 每 N 張 ping session 保活

  // fetch with hard timeout — NCL 偶爾 TCP 掛起不返回，不設限會卡住整個循環
  async function fetchWithTimeout(url, opts, ms) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try {
      return await fetch(url, { ...opts, signal: ctrl.signal });
    } finally {
      clearTimeout(tid);
    }
  }

  async function refreshToken() {
    for (let i = 0; i < REFRESH_RETRY; i++) {
      let isServerErr = false;
      try {
        const field = fn(NCL.next_key);
        const body = encodeURIComponent(field) + '=' + encodeURIComponent(NCL.rvt);
        const r = await fetchWithTimeout('/NCLSearch/Watermark/getToken', {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
          body
        }, 30000);
        if (r.status >= 500 && r.status < 600) { isServerErr = true; throw new Error('refresh status ' + r.status); }
        if (r.status !== 200) throw new Error('refresh status ' + r.status);
        const j = await r.json();
        if (!j.token || j.token.indexOf(':') < 0) throw new Error('bad response: ' + JSON.stringify(j));
        const [t, k] = j.token.split(':');
        if (!t || !k) throw new Error('empty token/key: ' + j.token);
        NCL.token = t; NCL.next_key = k; ST.refresh++;
        return;
      } catch (e) {
        ST.refresh_fail++;
        if (i < REFRESH_RETRY - 1) {
          // 5xx server 抖動 → 指數退避（8s, 16s, 32s, 64s）；其他錯誤用基礎間隔
          const delay = isServerErr ? REFRESH_RETRY_MS * Math.pow(2, i) : REFRESH_RETRY_MS;
          await new Promise(s => setTimeout(s, delay));
        } else throw e;
      }
    }
  }

  async function keepalive() {
    // 主動 fetch 一次當前 URL 重置 session idle timer（不消耗 token）
    try {
      await fetchWithTimeout(location.href, { credentials: 'include', cache: 'no-store' }, 15000);
      ST.last_keepalive = Date.now();
    } catch (e) {}
  }

  (async () => {
    const SLEEP_MS = 3000, TOKEN_LIFE = 50, PAUSE_429_MS = 300000;
    let sinceRefresh = 0;
    let sinceKeepalive = 0;
    const todo = [];
    for (let i = 0; i < NCL.bases.length; i++) {
      if (skipSet.has(i)) continue;
      if (!NCL.blobs[i] || !NCL.blobs[i].ok) todo.push(i);
    }
    if (args?.limit && todo.length > args.limit) todo.length = args.limit;
    ST.total = todo.length;
    for (const i of todo) {
      if (ST.stop || NCL.dlState.gen !== myGen) { ST.running = false; return; }
      let succeeded = false;
      for (let attempt = 0; attempt < 4 && !succeeded; attempt++) {
        try {
          const r = await fetchWithTimeout(NCL.bases[i].href + '&token=' + encodeURIComponent(NCL.token),
                                { credentials: 'include', cache: 'no-store' }, 30000);
          if (r.status === 429) {
            ST.last_429 = Date.now();
            await new Promise(s => setTimeout(s, PAUSE_429_MS));
            continue;
          }
          const ct = r.headers.get('content-type') || '';
          const ab = await r.arrayBuffer();
          const u = new Uint8Array(ab);
          if (ct.startsWith('image/') && u[0] === 0xFF && u[1] === 0xD8) {
            NCL.blobs[i] = { ok: true, pageno: NCL.bases[i].pageno, size: ab.byteLength, ab };
            ST.ok++; sinceRefresh++; sinceKeepalive++; succeeded = true;
          } else {
            // token 已消耗 / page 已消耗 → refresh 再試
            try {
              await refreshToken(); sinceRefresh = 0;
            } catch (e) {
              // refresh 連續失敗 → 致命，標記後外層循環會 stop
              ST.fatal = 'refresh failed: ' + (e?.message || String(e));
              break;
            }
          }
        } catch (e) { await new Promise(s => setTimeout(s, 2000)); }
      }
      if (!succeeded) {
        NCL.blobs[i] = { ok: false, pageno: NCL.bases[i].pageno, err: 'gave up' };
        ST.fail++; ST.consec_fail++;
      } else {
        ST.consec_fail = 0;
      }
      ST.done++;
      // 雪崩檢測：連續 N 張失敗 / fatal → 停
      if (ST.consec_fail >= MAX_CONSEC_FAIL || ST.fatal) {
        if (!ST.fatal) ST.fatal = 'consec_fail >= ' + MAX_CONSEC_FAIL;
        ST.running = false; ST.finished = Date.now();
        return;
      }
      // 主動 refresh token
      if (sinceRefresh >= TOKEN_LIFE) {
        try {
          await refreshToken(); sinceRefresh = 0;
        } catch (e) {
          ST.fatal = 'refresh failed (proactive): ' + (e?.message || String(e));
          ST.running = false; ST.finished = Date.now();
          return;
        }
      }
      // session keepalive
      if (sinceKeepalive >= KEEPALIVE_EVERY) {
        await keepalive(); sinceKeepalive = 0;
      }
      await new Promise(s => setTimeout(s, SLEEP_MS));
    }
    ST.running = false; ST.finished = Date.now();
  })();
  return { started: true, gen: myGen };
}
"""


@AdapterRegistry.register
class NCLRbookAdapter(BaseSiteAdapter):
    """臺灣國家圖書館 rbook.ncl.edu.tw NCLSearch 新版適配器。

    工作流：
      1. Playwright headed Chromium 打開 SearchDetail URL
      2. 用戶人工拖滑塊驗證碼（adapter 輪詢 .ImageC 等待，timeout 5 分鐘）
      3. 注入 prep JS 拿 fresh token 與 image base list
      4. 啟動 download JS fire-and-forget 循環（並發 1，3s/張，每 50 張 refresh）
      5. Python 端定期 poll dlState + 取回已成功的 blob 寫盤
      6. 全部完成或撞 429 後 stop，返回 ManifestNode

    斷點續傳：output_dir 已存在的 jpg 在 download_node 開始時填入 skip set；JS 循環跳過。
    """

    site_name = "臺灣國家圖書館 (NCL Taiwan, rbook.ncl.edu.tw)"
    site_id = "ncl_rbook"
    site_domains = ["rbook.ncl.edu.tw", "rbook2.ncl.edu.tw"]

    supports_iiif = False
    supports_images = True
    supports_text = False
    supports_pdf = False

    # captcha 等待上限（用戶過拼圖）
    CAPTCHA_TIMEOUT_MS = 300_000

    # poll 間隔（Python 端從 JS 端取進度的頻率）
    POLL_INTERVAL_S = 5.0

    def __init__(self, config=None):
        super().__init__(config)
        self._pw = None
        self._browser = None
        self._context = None
        self._viewer_pages: dict[str, object] = {}  # book_id -> page
        # cache metadata + bases 以避免重複過 captcha
        self._cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # URL 路由
    # ------------------------------------------------------------------
    @classmethod
    def can_handle(cls, url: str) -> bool:
        return any(d in url.lower() for d in cls.site_domains)

    def extract_book_id(self, url: str) -> str:
        """item= 參數是 server-side session token，每次訪問都會變。

        策略：對整個 SearchDetail URL 做 md5 取前 16 字符當穩定 ID。
        實際的台圖書號（Identifier_BookNo, 如 21681）等到 get_metadata 才能讀。
        """
        if "/Search/SearchDetail" not in url:
            raise MetadataExtractionError(
                f"暫只支援 /NCLSearch/Search/SearchDetail URL: {url}"
            )
        h = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
        return f"ncltw_{h}"

    # ------------------------------------------------------------------
    # Playwright lifecycle
    # ------------------------------------------------------------------
    def _check_playwright(self):
        if not HAS_PLAYWRIGHT:
            raise DownloadError(
                "playwright 是 NCL rbook 適配器的必須依賴。"
                "安裝：pip install playwright && playwright install chromium"
            )

    async def _ensure_browser(self):
        if self._browser and self._browser.is_connected():
            return
        self._check_playwright()
        self._pw = await async_playwright().start()
        try:
            # 必須 headed — 用戶要手動過拼圖驗證
            # --start-maximized + window-position 防止窗口被開到屏外/最小化
            self._browser = await self._pw.chromium.launch(
                headless=False,
                args=[
                    "--start-maximized",
                    "--window-position=100,50",
                    "--window-size=1400,900",
                ],
            )
        except Exception as e:
            await self._pw.stop()
            self._pw = None
            raise DownloadError(
                "Chromium 未安裝。請執行：playwright install chromium"
            ) from e
        # viewport=None → 跟隨真實窗口大小（與 --start-maximized 配合）
        self._context = await self._browser.new_context(viewport=None)

    async def close(self):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._pw = None
        self._viewer_pages.clear()

    # ------------------------------------------------------------------
    # 核心：開 viewer 並等待 captcha
    # ------------------------------------------------------------------
    async def _open_viewer(self, url: str, book_id: str):
        """開頁、等用戶過 captcha、跑 prep JS。返回 (page, prep_result)。

        如果 cache 已有 page 則直接復用（除非已關閉）。
        """
        if book_id in self._viewer_pages:
            page = self._viewer_pages[book_id]
            try:
                if not page.is_closed():
                    return page, self._cache[book_id]
            except Exception:
                pass

        await self._ensure_browser()
        page = await self._context.new_page()
        await page.goto(url, wait_until="domcontentloaded")

        logger.info("[ncl_rbook] 請在彈出的 Chromium 視窗中點「進入影像瀏覽」並拖完拼圖。")
        # 先等 URL 切到 viewer（image=1）。這代表用戶過了 captcha 並進入 viewer 頁。
        try:
            await page.wait_for_function(
                "() => location.href.indexOf('image=1') >= 0",
                timeout=self.CAPTCHA_TIMEOUT_MS,
            )
        except PWTimeout:
            await page.close()
            raise DownloadError(
                f"等待 captcha 完成超時（{self.CAPTCHA_TIMEOUT_MS // 1000} 秒），"
                f"URL 從未進入 viewer（image=1）"
            )
        logger.info("[ncl_rbook] 已進入 viewer 頁，等待 imageControl.js 初始化...")
        # viewer 進入後，imageControl.js 異步注入 .ImageC。給 60s 寬限。
        # 如果連這個都失敗，可能頁面結構變了，diagnostic 模式輸出 selectors 提示。
        try:
            # state="attached" — 只要 DOM 裡有就 OK，不要求 visible
            # （.ImageC 縮略圖列表可能在折疊面板中、初始為 display:none）
            await page.wait_for_selector(
                ".ImageC a[pageno]", timeout=60_000, state="attached"
            )
            # imageControl.js 異步加載 — 等 getImageKey 真的定義出來
            await page.wait_for_function(
                "() => typeof getImageKey === 'function' && !!document.getElementById('ImageDisplay')",
                timeout=30_000,
            )
        except PWTimeout:
            # 診斷：列出當前 DOM 主要結構，便於修 selector
            diag = await page.evaluate(
                """() => {
                  const out = {
                    url: location.href,
                    title: document.title,
                    has_ImageDisplay: !!document.getElementById('ImageDisplay'),
                    has_getImageKey: typeof getImageKey === 'function',
                    imageC_count: document.querySelectorAll('.ImageC').length,
                    imageC_a_count: document.querySelectorAll('.ImageC a').length,
                    a_pageno_count: document.querySelectorAll('a[pageno]').length,
                    img_count: document.querySelectorAll('img').length,
                    iframe_count: document.querySelectorAll('iframe').length,
                    main_classes: [...document.querySelectorAll('div[class]')].slice(0, 20).map(d => d.className),
                  };
                  return out;
                }"""
            )
            await page.close()
            raise DownloadError(
                f"viewer 進入但 .ImageC a[pageno] 未出現。Diagnostic: {diag}"
            )

        # 跑 prep JS
        prep = await page.evaluate(_NCL_PREP_JS)
        if not prep.get("ok"):
            await page.close()
            raise DownloadError(f"NCL prep 失敗: {prep}")
        logger.info(
            f"[ncl_rbook] prep OK: title={prep['md']['title']}, "
            f"bookno={prep['md']['bookno']}, pages={len(prep['bases'])}"
        )

        self._viewer_pages[book_id] = page
        self._cache[book_id] = prep
        return page, prep

    # ------------------------------------------------------------------
    # Metadata + image list
    # ------------------------------------------------------------------
    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        # 支援 augmented book_id 'ncltw_<hash>|<url>'，也支援裸 bid_short（cache 已有時）
        bid, _, url = book_id.partition("|")
        if bid not in self._cache:
            if not url:
                raise MetadataExtractionError(
                    "首次呼叫 get_metadata 需 augmented book_id 'ncltw_<hash>|<url>'"
                )
            await self._open_viewer(url, bid)
        prep = self._cache[bid]
        return self._build_metadata(bid, prep, {})

    async def get_image_list(self, book_id: str) -> List[Resource]:
        if book_id not in self._cache:
            raise MetadataExtractionError(
                "先 discover_structure 觸發 _open_viewer"
            )
        prep = self._cache[book_id]
        bookno = prep["md"]["bookno"]
        out = []
        for i, b in enumerate(prep["bases"]):
            out.append(Resource(
                url=b["href"],  # 不含 &token=，僅供記錄；實際下載走 JS 循環
                resource_type=ResourceType.IMAGE,
                order=i + 1,
                page=str(b["pageno"]),
                filename=f"{bookno}_{i + 1:04d}.jpg",
            ))
        return out

    async def discover_structure(
        self,
        book_id: str,
        index_id: str = "",
        depth: int = 1,
        progress_callback: Callable[[str, str], None] = None,
    ):
        """需要原始 URL — 從 progress_callback 或外部傳入。

        因為 BaseSiteAdapter 的 discover_structure 沒接收 URL 參數，
        當前實作要求調用方在 `book_id` 後綴附 URL：book_id = "ncltw_<hash>|<url>"。
        """
        # parse augmented book_id
        bid, _, url = book_id.partition("|")
        if not url:
            raise MetadataExtractionError(
                "discover_structure 需要 augmented book_id 'ncltw_<hash>|<url>'"
            )
        await self._open_viewer(url, bid)
        # 重用 base class 的 legacy discover（會調 get_image_list）
        # 此時 self._cache 已就緒，get_image_list 能拿到 bases
        # 換掉 self.get_metadata 的 url 依賴：直接從 cache 拿
        return await self._discover_from_legacy(bid, index_id)

    async def _read_detail_page(self) -> dict:
        """從 viewer 頁讀詳細資料表格（正題名/作者/版本/卷數 等）。

        viewer 頁右側通常會渲染這些字段；如果讀不到就返回空 dict。
        """
        # 預留 hook，後續可拓展。目前 prep 已抓 hidden inputs，足夠。
        return {}

    def _build_metadata(self, book_id: str, prep: dict, extra: dict) -> BookMetadata:
        md = prep["md"]
        meta = BookMetadata(
            source_id=md.get("bookno") or book_id,
            source_url=md.get("url", ""),
            source_site=self.site_id,
            title=md.get("title", ""),
            call_number=md.get("call_number", ""),
            collection_unit=md.get("rights_owner") or "國家圖書館 (臺灣)",
            raw_metadata={
                "bookno": md.get("bookno", ""),
                "accession": md.get("accession", ""),
                "source": md.get("source", ""),
                "rights_owner": md.get("rights_owner", ""),
                "rights_owner_country": md.get("rights_owner_country", ""),
                "viewer_url": md.get("url", ""),
            },
        )
        return meta

    # ------------------------------------------------------------------
    # 下載
    # ------------------------------------------------------------------
    async def download_node(
        self,
        book_id: str,
        node: ManifestNode,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] = None,
        limit: Optional[int] = None,
    ) -> ManifestNode:
        """啟 JS 下載循環 → 定期 poll 進度與取回已成功 blob → 寫盤。

        limit: 若給定，JS 端最多下 limit 張（用於烟測）。
        """
        # 從 augmented book_id 取 URL（與 discover_structure 一致）
        bid, _, url = book_id.partition("|")
        if not url:
            # 嘗試從 cache 找 — 假設 discover 已跑過
            if bid in self._cache:
                url = self._cache[bid]["md"]["url"]
            else:
                raise DownloadError(
                    "需要 augmented book_id 'ncltw_<hash>|<url>'"
                )

        page, prep = await self._open_viewer(url, bid)
        bookno = prep["md"]["bookno"]
        total = len(prep["bases"])

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 斷點：掃 output_dir 已有的 jpg，計算 skip set（按 pageno 索引）
        skip = []
        for i, b in enumerate(prep["bases"]):
            fp = output_dir / f"{bookno}_{i + 1:04d}.jpg"
            if fp.exists() and fp.stat().st_size > 1024:
                skip.append(i)
        already_done = len(skip)
        if already_done:
            logger.info(f"[ncl_rbook] 已存在 {already_done}/{total} 張，跳過")

        # 啟 JS 下載循環
        start = await page.evaluate(_NCL_DL_JS, {"skip": skip, "limit": limit})
        if not start.get("started"):
            raise DownloadError(f"啟動下載循環失敗: {start}")
        logger.info(f"[ncl_rbook] 下載循環啟動，gen={start['gen']}, todo={total - already_done}")

        node.status = NodeStatus.DOWNLOADING
        node.total_items = total

        # 定期 poll：1) 拿狀態；2) 把已成功且未寫盤的 blob 取回寫盤
        flushed = set(skip)  # 已寫盤的 idx
        consec_poll_fail = 0
        MAX_POLL_FAIL = 5  # 連續 N 次拿不到 dlState 就退出（瀏覽器/頁面已關閉）
        last_done = -1
        stale_polls = 0
        MAX_STALE_POLLS = 24  # 24 * 5s = 2 min 沒進度就視為 hang
        while True:
            await asyncio.sleep(self.POLL_INTERVAL_S)
            # 頁面關閉 → 立刻退出
            if page.is_closed():
                logger.error("[ncl_rbook] 頁面已關閉，退出 poll loop")
                break
            try:
                st = await page.evaluate(
                    "() => ({ ...window.NCL.dlState, bases_len: window.NCL.bases.length })"
                )
                consec_poll_fail = 0
            except Exception as e:
                consec_poll_fail += 1
                logger.warning(f"[ncl_rbook] poll dlState 失敗 ({consec_poll_fail}/{MAX_POLL_FAIL}): {e}")
                if consec_poll_fail >= MAX_POLL_FAIL:
                    logger.error("[ncl_rbook] poll 連續失敗，退出 loop")
                    break
                continue

            # flush 已 ok 的 blob 到磁盤
            new_flushed = await self._flush_blobs(page, prep, output_dir, flushed)
            if new_flushed or st.get('fatal'):
                rf_fail = st.get('refresh_fail', 0)
                fatal = st.get('fatal')
                msg = (
                    f"[ncl_rbook] flush {len(new_flushed)} 張；"
                    f"進度 {len(flushed)}/{total}; "
                    f"JS: done={st.get('done', 0)} ok={st.get('ok', 0)} "
                    f"fail={st.get('fail', 0)} refresh={st.get('refresh', 0)}"
                )
                if rf_fail:
                    msg += f" refresh_fail={rf_fail}"
                if fatal:
                    msg += f" FATAL={fatal}"
                logger.info(msg)

            if progress_callback:
                progress_callback(len(flushed), total)

            # hang 檢測：done 連續 N 次 poll 不變
            cur_done = st.get('done', 0)
            if cur_done == last_done:
                stale_polls += 1
                if stale_polls >= MAX_STALE_POLLS:
                    logger.error(
                        f"[ncl_rbook] JS 循環 hang：done={cur_done} 連續 "
                        f"{MAX_STALE_POLLS} 次 poll 不變（{MAX_STALE_POLLS * self.POLL_INTERVAL_S}s），主動退出。"
                        f" 重跑會從斷點續傳。"
                    )
                    try:
                        await page.evaluate("() => { if (window.NCL?.dlState) window.NCL.dlState.stop = true; }")
                    except Exception:
                        pass
                    break
            else:
                stale_polls = 0
                last_done = cur_done

            if not st.get("running"):
                # 最後 flush 一次
                await self._flush_blobs(page, prep, output_dir, flushed)
                if progress_callback:
                    progress_callback(len(flushed), total)
                logger.info(
                    f"[ncl_rbook] 循環結束。最終：ok={st.get('ok', 0)} "
                    f"fail={st.get('fail', 0)} flushed={len(flushed)}/{total}"
                )
                break

        node.downloaded_items = len(flushed)
        node.failed_items = total - len(flushed)
        node.status = NodeStatus.COMPLETED if node.failed_items == 0 else NodeStatus.FAILED
        node.local_path = str(output_dir)
        return node

    async def _flush_blobs(self, page, prep: dict, output_dir: Path,
                           flushed: set) -> List[int]:
        """把 window.NCL.blobs 中 ok 且未寫盤的取回，base64 解碼後寫到磁盤。

        每批最多取 5 張（避免單次 evaluate 返回過大；NCL 單張 ~200-400KB，
        base64 後 ~270-540KB，5 張 ~1.5-2.7MB JSON）。
        """
        new_indexes = []
        bookno = prep["md"]["bookno"]
        total = len(prep["bases"])

        # 拿到待 flush 的 idx 列表
        idxs = await page.evaluate(
            """(args) => {
              const flushedSet = new Set(args.flushed);
              const out = [];
              for (let i = 0; i < window.NCL.blobs.length; i++) {
                if (flushedSet.has(i)) continue;
                if (window.NCL.blobs[i]?.ok) out.push(i);
                if (out.length >= args.cap) break;
              }
              return out;
            }""",
            {"flushed": list(flushed), "cap": 5},
        )
        if not idxs:
            return []

        for i in idxs:
            # 單張取回 base64
            b64 = await page.evaluate(
                """(idx) => {
                  const ab = window.NCL.blobs[idx].ab;
                  const u8 = new Uint8Array(ab);
                  // 大文件分塊轉 base64
                  let s = '';
                  for (let p = 0; p < u8.length; p += 0x8000) {
                    s += String.fromCharCode.apply(null, u8.subarray(p, p + 0x8000));
                  }
                  return btoa(s);
                }""",
                i,
            )
            data = base64.b64decode(b64)
            fp = output_dir / f"{bookno}_{i + 1:04d}.jpg"
            fp.write_bytes(data)
            flushed.add(i)
            new_indexes.append(i)

            # 釋放 JS 端記憶體（避免大本書 OOM）
            await page.evaluate(
                "(idx) => { if (window.NCL.blobs[idx]) window.NCL.blobs[idx].ab = null; }",
                i,
            )
        return new_indexes


def prep_full_metadata(extra: dict) -> dict:
    """佔位 — 留給未來從詳情頁解析作者/版本/卷數等。"""
    return extra or {}
