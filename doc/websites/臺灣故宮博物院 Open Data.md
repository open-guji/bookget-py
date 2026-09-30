# 國立故宮博物院 Open Data（臺灣故宮博物院）

國立故宮博物院（台北）的「典藏資料檢索 Open Data 專區」，公開全院書畫、器物典藏品的中英文資料與高解析影像，影像以 CC BY 4.0 授權，可自由重製、改作、商業使用（須標示來源）。

- 網站連結：https://digitalarchive.npm.gov.tw/opendata/
- 分享協議：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.zh_TW)（頁面右側「著作權聲明」欄給出每件作品的標示字串）
- 書畫（dep=P）約 38,600 筆、器物（dep=U）約 70,000 筆；書畫中冊頁的每一開通常是一筆獨立紀錄
- 資源類型：法書、法帖、拓片、繪畫、善本冊頁、器物等
- 支持 IIIF 協議（Image API 2.0 level2），可用 bookget 下載原始解析度影像並合成 PDF

## 搜尋與瀏覽

- 檢索頁：https://digitalarchive.npm.gov.tw/opendata/Pub/Search（書畫）、…/Collection/Search（器物）
- 輸入關鍵字檢索；可依「分類」（法書、法帖、拓片、繪畫…）、「朝代」、「作者」、「形式」（冊、卷、軸）篩選
- 不需註冊登入

## 每件作品能看到什麼

| 欄位 | 說明 | 示例 |
|------|------|------|
| 品名 | 作品名稱（含朝代、作者、形式） | 宋榻大觀帖（九）　冊　晉王獻之吳興帖 |
| 作者 | 中英文人名 | 王獻之,Wang Xianzhi |
| 文物統一編號 | 院藏登錄號；冊頁各開共用前綴，後綴 N000000000 為冊級 | 故帖000156N000000012 |
| 分類／書體／創作時間／數量 | 基本資料 | 法帖／行書／宋／一幅 |
| 典藏尺寸 | 本幅、隔水、拖尾等尺寸 | 本幅 27.5x39.2 公分 |
| 質地 | 材質 | 紙 |
| 釋文 | 作品文字 | 吾十一日發吳興… |
| 題跋資料 | 題跋者、位置、款識、印記 | 董其昌 … |
| 印記資料 | 類別、印主、印文 | 收傳印記 … |
| 著作權聲明 | 引用時須標示的字串 | …。國立故宮博物院，台北，CC BY 4.0 @ www.npm.gov.tw |

- 可線上以 IIIF 檢視器翻閱影像；影像原始尺寸多在 3,000–15,000 px
- 無官方 PDF；`bookget pdf` 可將下載的影像合成 PDF 並附上資料表
- 無 OCR 全文，但「釋文」欄常收錄作品文字

## 示例

- 詳情頁（書畫）：https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=1528&dep=P&mode=full
- 詳情頁（器物）：https://digitalarchive.npm.gov.tw/opendata/Collection/Detail?id=11&dep=U
- IIIF 檢視器：https://digitalarchive.npm.gov.tw/opendata/IIIFViewer?id=1528&dep=P&imageName=

---

# 開發者文檔

## URL 結構

### 詳情頁
```
https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id={oid}&dep={dep}&mode=full     # 書畫 dep=P
https://digitalarchive.npm.gov.tw/opendata/Pub/Detail/{oid}?dep={dep}
https://digitalarchive.npm.gov.tw/opendata/Pub/DetailEng/{oid}?dep={dep}               # 英文版
https://digitalarchive.npm.gov.tw/opendata/Collection/Detail?id={oid}&dep=U            # 器物
```
- `oid`：數字流水號；`dep`：部門代碼（P 書畫、U 器物）。bookget 的 book_id 為 `{dep}{oid}`，如 `P1528`
- `mode=full` 才會輸出「題跋」「印記」等完整分頁

### IIIF Manifest
```
https://digitalarchive.npm.gov.tw/opendata/Integrate/GetJson?cid={oid}&dept={dep}&imageName=
```
- IIIF Presentation 2 manifest，`sequences[0].canvases[].images[0].resource.service.@id` 為影像服務
- 約 1,200 筆紀錄此端點回傳空白內容，此時改從詳情頁圖庫的 `data-image-name` 取得影像名稱

### 影像（IIIF Image API 2）
```
https://iiifod.npm.gov.tw/iiif/2/{prefix}%2F{imageName}/full/full/0/default.jpg
```
- `imageName` 如 `K2D000156N000000012PAA`，`prefix` 為其前三碼（`K2D`）
- `full/full` 即原始解析度；支援 jpg / png / tif
- 該主機的 TLS 憑證缺少 Subject Key Identifier，Python 3.13+ 需關閉 `VERIFY_X509_STRICT`（bookget 已處理）

## 搜尋 API

```
POST https://digitalarchive.npm.gov.tw/opendata/Pub/Search        Content-Type: application/json
{"RegisterType": "法帖" | null, "SearchContent": "關鍵字" | null, "IndexYear": null,
 "WestBeginYear": 0, "WestEndYear": 0, "YearDisplay": "", "RegisterTypeEng": null,
 "PageInfo": {"PageIndex": 1, "PageSize": 500, "PageCount": 1}}
```
- 回應為 HTML 片段：每筆 `onclick="Detail('16764', 'P')"` + `<div class="card-title">品名</div>`；`"PageCount":N` 給出總頁數
- `RegisterType` 依「分類」過濾（繪畫 / 法書 / 法帖 / 拓片 / 成扇 / 其他）；`SearchContent` 關鍵字也能命中文物統一編號前綴（`故帖000156` → 該冊全部開頁記錄）
- bookget：`bookget search npm_taipei "category:法帖" --limit 500`；`PalaceMuseumTaipeiAdapter.search_all()` 取全部頁

## 元數據獲取

詳情頁為伺服器端渲染 HTML，`bookget/adapters/other/taiwan.py` 的 `parse_detail_page()` 以正則解析：

| 欄位 | 提取方式 |
|------|---------|
| 品名 | `<h2 class="text-title">` |
| 基本資料 | `#details-1` 中每個 `<th>/<td>`（含「文物統一編號」；多個編號時保留第一個，其餘存為「文物統一編號（其他）」） |
| 典藏尺寸／質地／題跋／印記／保存維護 | `#details-2 … #details-9` 表格，`header` + `rows`；題跋列內嵌的印記子表折疊為一欄 |
| 影像名稱 | 圖庫 `data-image-name` |
| 著作權聲明 | 「著作權聲明」欄；作品品名中的 U+F6A4 等 PUA 合字會轉回正確字元 |

`BookMetadata` 對應：title／creators（作者「中,英」拆分）／dynasty（由品名開頭推得）／date=創作時間／category=分類／doc_type=書體／call_number=文物統一編號／dimensions／notes（釋文）／provenance（題跋、印記）；完整解析結果放在 `raw_metadata`，下載時另存為 `raw.npm_taipei.json`。

## 下載

完整流程指南見 [doc/ARCHIVAL_PDF.md](../ARCHIVAL_PDF.md)。

```bash
# 單筆紀錄
bookget download "https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=1528&dep=P&mode=full" -o ./npm --pdf
# 整件作品（冊頁的全部開頁紀錄）+ LuaLaTeX 排版資料表
bookget download "https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=16797&dep=P&mode=full" -o ./npm --album --pdf --pdf-engine latex
bookget pdf ./npm/P1528 --engine latex     # 已下載的目錄也可事後合成
```

- 影像按名稱排序（`…PAA`、`…PAB`…），以 `001_<imageName>.jpg` 命名；下載目錄另存 `raw.npm_taipei.json`（完整解析結果，含中英文分頁）
- **整件作品（`--album`）**：冊頁每一開是獨立紀錄，且各紀錄的 manifest／圖庫列出的影像互有重疊。bookget 以統一編號前綴檢索出全部開頁紀錄，按影像編號前綴（`label[:9]`，如 `K2D000156`）分組，影像依編號排序去重，每幅影像歸屬於編號 N 段相同的開頁紀錄（含該紀錄「其他」編號），總紀錄為編號以 `N000000000` 結尾且品名最短者
- `--pdf` / `bookget pdf` 生成 `pdf/NPM-<統一編號>_<品名>.pdf`（整冊 `NPM-故帖000156_宋榻大觀帖_九_冊.pdf`，單開 `NPM-故帖000156N000000012_…吳興帖.pdf`，可直接上傳 Wikimedia Commons）：JPEG 原樣嵌入不重壓、Info/XMP 元數據（含 ObjectNumber、Attribution、IIIFManifest 等自訂鍵）、每開書籤、頁碼標籤=影像名、附加 metadata.json 與原始紀錄；末尾附「文物資料表」。`--engine latex` 用 LuaLaTeX 排版（與維基共享資源上傳批次相同版式，需 TeX Live + 思源宋體）；預設 native 引擎以 Pillow 栅格化資料表（無 CJK 字型時跳過）。裝有 PyMuPDF 時自動校驗影像逐位元一致、無空白頁
- 已上傳維基共享資源的批次（法帖、法書、拓片，約 3,900 件）即以此流程製作；民國作品（非公有領域）需自行排除
