# 当前路线：bookget-py 完全体（纵深优先）

> 总计划见 overview 工作流：`overview/项目进展/资源下载/bookget-完全体-总计划.md`
> 站点矩阵：`overview/项目进展/资源下载/站点覆盖矩阵.md`

## Phase 1 — 文本/元数据/搜索三件套

### ✅ 1.1 繁简/异体字归一化共享模块（done 2026-05-21）
- 新建 `bookget/shared/cjk_match.py`，把 ctext 与识典两份重复逻辑合并为单一实现
- ctext.py / shidianguji.py 改为引用，去重 ~560 行
- 识典顺带获得：单字异体替换（注↔註）+ strict 前缀匹配（原先缺）
- 新增 `tests/test_cjk_match.py`（21 例）；全套 320 passed（11 个 pre-existing 失败与本次无关）

### ✅ 1.4 识典 search()/match_book()（done — 已存在 + 现复用共享模块）
- 浏览器复用 `_ensure_browser/_close_browser`、search 拦截 `/search/book/v1`、match 三级作者匹配均已实现

### 🟡 1.2 元数据字段覆盖审计（基本完成）
审计结论：
- **全字段(古籍schema)**：nlc_guji（金标准）
- **较全**：harvard / base_iiif（含 stanford/berkeley/european-BnF/BL/BSB 继承）/ ndl / kyoto / princeton / ctext / hanchi / taiwan / shidianguji / wikisource / archive_org
- **偏薄**：nlc_read（PDF）、ncl_rbook（Playwright）、wikimedia_commons
- **固有限制**：IIIF/欧美源 manifest 无「朝代/四部分类」，无法臆造，非缺陷

已处理：
- ✅ wikimedia_commons：删除其自带的第 3 份（仅 12 项、无 OpenCC）异体表 → 改用 `cjk_match`，补上繁简转换（原先 论语 不匹配 論語）。**至此 ctext/识典/wikimedia 三处变体逻辑全部统一**。
- nlc_read：已设 source_url/site + title + collection_unit；详情页深度字段（作者/年代）需 read.nlc.cn 实样（IP 受限），暂记待补。
- ncl_rbook：已设 source 字段 + title + call_number + collection_unit + accession；更多书志字段需 rbook 实样（滑块验证），暂记待补。

### ✅ 1.5 测试夹具 + 冒烟测试 + 套件转绿（done 2026-05-21）
- 新建 `tests/fixtures/site_urls.yaml`（19 个站点真实 URL 形态，来源 bookget Wiki 04/05 + 适配器 docstring）
- 新建 `tests/test_site_routing.py`：参数化离线冒烟测试（每站 get_for_url 路由正确 + extract_book_id 非空 + 覆盖率守卫：新增适配器若漏登记夹具会失败）
- 清理全部 11 个 pre-existing 失败测试（**全是测试过时，非产品 bug**）：
  - NCL 台湾：`TestNCLTaiwanAdapter`（引用已删的 `taiwan.NCLTaiwanAdapter`）→ 改写为 `TestNCLRbookAdapter`（ncl_rbook 离线路由/ID）
  - hanchi×2：parser 已改为「未知校勘图标/ span 记 WARNING 而非 raise」（优雅降级）→ 改测断言宽容行为（`(qz.gif)` 字面量 / `【…】`）
  - ShidianGujiParser×3：parser API 已改为吃 paragraphs/v2 段落 dict（content 为 JSON）→ 按真实 API 重写
- `pyproject.toml` dev 依赖加 `pyyaml>=6.0`
- 结果：**离线全套 368 passed, 0 failed**（含 21 cjk_match + 39 路由/抽取冒烟）

### ⏳ 1.3 现有文本站点 StructuredText 质量抽样校验（待办，需联网）
- ctext（API）/ 维基文库（API/dump）/ 识典（Playwright）/ 漢籍 的章节层级、夹注、Markdown 输出抽样
- 偏 QA 性质，非纯代码改动；可与 Phase 3 起步并行

---

# 测试基建（done 2026-05-22）

> 详见 `DEVELOPER.md` 的「测试策略」。三层：L1 离线路由/ID（`test_site_routing.py` + `site_urls.yaml`，每站多 URL 形态 + 覆盖率守卫）、L2 适配器单元、L3 真连下载路径（`test_live_download.py` + `live_urls.yaml`，`live` 标记，默认排除）。
> - `pytest` = 离线（427 passed）；`pytest -m live` = 真连（7 passed：bodleian/vatican/cambridge/ndl/bsb/ctext/wikisource）
> - `pyproject.toml` 加 `[tool.pytest.ini_options]`：`asyncio_mode=strict` + `addopts="-m 'not live'"` + `live` marker；旧的 3 个 ctext + hanchi live 测试已打 `live` 标记
> - **多 URL 形态抓出 2 个真实 bug 并修复**：
>   - `registry.get_for_url`：通用 IIIF 截胡任意 `*manifest*.json` → 改为「域名专属适配器优先于无域名 catch-all」
>   - NDL 元数据漏主标题字段 `0001Dtct`（导致 title 为空）→ 补上 + 加 katakana 兜底 + 映射四部分类 `0022Dtct`
> - 新增适配器规约：必在 `site_urls.yaml` 登记（守卫强制）；建议在 `live_urls.yaml` 加一条真实 URL 并本地 `pytest -m live` 验证

# Phase 3 — IIIF 站点广度补全（进行中）

> 标准 IIIF v2/v3：URL→manifest 映射 + 复用 base_iiif 下载/元数据。新站只需 site_*/extract_book_id/manifest_url_template，并在 `tests/fixtures/site_urls.yaml` 加一条（覆盖率守卫会强制）。PyInstaller spec 用 `collect_submodules('bookget.adapters')` 自动收录，无需手改。

### ✅ 第一批（done 2026-05-21，manifest 均已 live 验证）
- `bodleian` 牛津博德利：`iiif.bodleian.ox.ac.uk/iiif/manifest/{uuid}.json`；live 验证 565 图 ✓
- `vatican` 梵蒂冈 DigiVatlib：`digi.vatlib.it/iiif/{shelfmark}/manifest.json`；live 验证 111 图 ✓
- `cambridge_cudl` 剑桥 CUDL：`cudl.lib.cam.ac.uk/iiif/{item_id}`；manifest IIIF v2 已验证
- 离线全套 **374 passed**

### ✅ 第二批（done 2026-05-22，live 验证）
- `berlin_sbb` 柏林国立：`content.staatsbibliothek-berlin.de/dc/{PPN}/manifest`（PPN 取自 `?PPN=`）；含 Origin/Referer 头；live 验证（Hanlin papers ~450 图）
- `kokusho` NIJL 国書DB：`kokusho.nijl.ac.jp/biblio/{BID}/manifest`（静态模板，无需 API）；live 验证 ✓
- 适配器数 23 → **25**；live 全套 **9 passed**

### ✅ 第三批（done 2026-05-22，live 验证）
- `smithsonian` 史密森尼：`ids.si.edu/ids/manifest/{IDSID}`（静态模板）；含 Origin/Referer；live 验证 ✓
- 适配器数 25 → **26**；live 全套 **10 passed**

### ✅ 第四批（done 2026-05-22，借助 chrome-devtools MCP）
- 用真实 Chrome 抓页面网络请求，发现两站 manifest **其实可推导**（不必 HTML-scrape）：
  - `emuseum` e国宝：`/iiifapi/{contentsID}/manifest.json`，`contentsID = base + pad3(part) + pad3(pict)`；浏览器验证 3 项 + **live 验证 31 图**（aiohttp 早先的 SSL 报错是偶发，重测通过）
  - `khirin` 国立歴史民俗博物館：`/iiif/rekihaku/{id}/manifest.json`（从真实 UV viewer 请求确认）；离线路由已测；**live 待一个有图样本**（SPA 列表抓不到 item id，静态样本 00002-8 无图 500）
- 适配器 26 → **28**；离线 **453 passed**；live **11 passed**
- **方法论沉淀**：SPA/动态 manifest 站，用 chrome-mcp `new_page` + `list_network_requests` 抓真实 manifest 请求 → 多半能反推静态模板，比 HTML-scrape 更稳。

### ✅ khirin 改对了（done 2026-05-22，live 验证）
- 用户给真实 item `https://khirin-a.rekihaku.ac.jp/nmjh_nishikie/h-22-1-1-1` → chrome-mcp 抓到真 manifest `/manifests/nishikie/H-22-1-1-1.json`（**按集合不同、不可推导**，我之前的 `/iiif/rekihaku/{id}` 假设是错的）
- 改写为 **HTML-scrape**：manifest URL 在静态 HTML 里（`manifest=...json`），aiohttp 抓页面 regex 出来再取 manifest（无需浏览器）。**live 通过**
- live 全套 **12 passed**

### ✅ Phase 4 自定义 API 站（done 2026-05-22，用户给真实 URL + chrome-mcp 抓接口 + live 验证）
- `hkust` 香港科技大学：bib `/bib/{id}` → 抓 sPath（`view_book('…')`）→ `bookreader/getfilelist.php?path={sPath}` → `obj/{sPath}/*.jpg`；自写 get_image_list + download_node；**live 通过**
- `taiwan_ebook` 台湾华文电子书库：reader 页抓 `viewer.html?file={path}` → PDF 直下（`/ebkFiles/{id}/{id}.PDF`），标题取麵包屑 `active section`；**NCL 证书缺 SKI**，get_session 放宽 `VERIFY_X509_STRICT`（仍验链）；**live 通过**
- 适配器 29 → **31**；离线 **461 passed**；live **14 passed**

### ✅ 非纯 IIIF（done 2026-05-22，live 验证）
- `loc` 美国国会图书馆：`item/{id}/?fo=json` → `resources[]`(卷)→`files[]`(页)，每页取 jpeg `full/pct:100/0/default.jpg`；自写 get_metadata/get_image_list/download_node；live 验证（道古堂集 1051 页）
- `onb` 奥地利国家图书馆：旧 OnbViewer 已迁 `viewer.onb.ac.at`，背后是 **IIIF v3**（`api.onb.ac.at/iiif/presentation/v3/manifest/{doc}`，doc 形如 `ABO_+Z…`）。bookget 旧 imageData 接口已过时
  - **base_iiif 补了 IIIF v3 解析**：`_extract_label` 处理 v3 lang-map（`{none:[...]}`）；`_parse_manifest_images` 加 v3 分支（`items[]`canvas→annotation `body`→ImageService3，size 用 `max`）。v2 路径不变
  - live 验证 194 图
- 适配器 31 → **33**；离线 **473 passed**；live **16 passed**

### ✅ 日本 IIIF 续批（done 2026-05-22，**关键：bookget wiki 04 页给了真实 item URL**，解锁 SPA 站）
- `keio` 庆应义塾：item 页 HTML 内嵌 `…/iiif/{GRP}/{ID}/manifest.json`（HTML-scrape，同 khirin）；wiki item `ja/kanseki/110x-24-1`；live 验证
- `ryukoku` 龙谷：`/page/{id}`→`/iiif/{id}/1/manifest.json`（可推导）；live 验证 123 图（春秋左伝註疏）
- **base_iiif 健壮性修复**：`get_iiif_manifest` 用 `response.json(content_type=None)`——龙谷把 manifest 当 text/html 发，aiohttp 严格 .json() 会炸（浏览器宽容）。利好所有 IIIF 站
- 适配器 33 → **35**；离线 **481 passed**；live **18 passed**
- `toyobunko` 东洋文库（dsr.nii.ac.jp）：`/toyobunko/{item}/{vol}/manifest.json`（可推导 IIIF v2）；live 验证 23 图（圓明園…西洋樓圖）。适配器 35→**36**，live **19 passed**
- ⏳ **TNM 东京国立博物馆**：图走 **Zoomify 瓦片**（`/tiles/{code}/TileGroup0/{z}-{x}-{y}.jpg` + ImageProperties.xml）+ jsessionid → 需先做**瓦片拼接引擎**（与省级方志 DeepZoom 同类，高杠杆，单列）
- ⏳ wiki 04 还有 item URL 待做：宫内厅 `db2.sido.keio.ac.jp/kanseki/bib_frame?id=006754`、东大东文研 `shanben.ioc.u-tokyo.ac.jp/...`、国立公文书馆、奎章阁 `kyudb.snu.ac.kr/...`、高丽、俄国 `viewer.rsl.ru/...`、越南、IDP

### 📋 grind 站（未落地，结构线索）
- **广州大典** gzdd.gzlib.org.cn：可达；`api/Search/Detail` 元数据免登录，`api/Search/ReadBook` 页图 **401 需 Bearer+fingerprint（登录）** → 登录阶段
- **早稻田** wul.waseda.ac.jp/kotenseki：**纯逐页 JPG，无 PDF**（whole/per-vol PDF 均 404）。图 `archive.wul.waseda.ac.jp/kosho/{grp}/{id}/{id}_{vol:04d}/{id}_{vol}_p{page:04d}s.jpg`（`s`=小图）；冊数在页面（如「4冊」）但**每冊页数 JS 视viewer 端、archive 主机禁 CORS** → 需逐页探 404 或找索引，grind
- **庆应 dcollections**：manifest `dcollections.lib.keio.ac.jp/sites/default/files/iiif/{grp}/{id}/manifest.json`（IIIF v2，已验证有效，如 `TKU/Ud0026`）。但 item viewer 是 SPA、item 链接 JS 隐藏，detail URL→id 抓不到。**注意：generic_iiif 已能直接吃 Keio 的 manifest URL**，专属适配器只为 detail URL，价值有限
- **教训**：SPA 站从沙箱「翻列表找 item」基本走不通（CUHK/HKU/Keio/广州大典列表都如此）。**最快路径＝用户直接给真实 item/viewer URL**（HKUST/台湾/khirin 都是这样一次过的）

### ✅ Zoomify 瓦片拼接引擎 + TNM（done 2026-05-22，live 验证拼图）
- 新建 `bookget/downloaders/tiles.py`：Zoomify 瓦片金字塔 → 取顶层全部瓦片 → Pillow 拼整图
  - tier 数学经 NUMTILES 校验（5760×3840×256 → 474 瓦片，顶层 23×15，tier5）；`TileGroup = floor(globalIdx/256)`
  - 离线单测 `tests/test_tiles.py`（math 确定性，5 例）
  - Pillow 入 `pyproject.toml` `[tiles]` extra
- `tnm` 东京国立博物馆：`/dlib/pages/{id}` 取页（需先 GET 详情页拿 JSESSIONID）+ 每页 Zoomify 拼接；**live 验证拼出 5760×3840**（傷寒論）
- 新增 live 测试 `kind: tiled`（拉首页瓦片拼接 + 校验图像尺寸）
- 适配器 36 → **37**；离线 **492 passed**；live **20 passed**
- ⚠️ PyInstaller：tiles.py 里 `from PIL import Image` 是惰性导入，frozen 构建可能漏 Pillow → 需要时把 `PIL` 加进 cli.spec/ui.spec hiddenimports
- 💡 省级方志（四川/云南/湖北/江苏）的 DeepZoom（`tiles/infos.json`）可复用此引擎接一个变体

### 🟡 受限站
- `hku` 香港大学：适配器在（IIIF `/service/api/iiif/manifest/{id}`），离线路由已测。**用户与沙箱均访问不通**（站点疑下线/限制）→ **暂停 live**，适配器保留
- `cuhk` 香港中文：**WAF 全拦**（Chrome/WebFetch 从沙箱均 403）。item `/en/item/cuhk-3325845`，bookget 法：抓页内 `pages[]` 拼 `/iiif/2/{id}/...`（非 manifest）。**归入反爬阶段**（需 cookie/header + 可达网络），未实现
- 适配器 **29**（hku 计入；cuhk 未实现）

### ⏳ 待办
- HKU/khirin live：网关恢复 / 找有图样本后补进 live_urls 验证
- khirin live：找一个有图的 khirin-a 项（走 khirin-ld 检索 / database 列表 API）补进 live_urls
- **非纯 IIIF（需自写 get_image_list）**：奥地利 ONB（OnbViewer JSON API + `w=2400&q=70` 拼图）、LOC（loc.go 自定义）
- **「手贴 manifest」站**（斯坦福 purl、京大、駒澤、关西、庆应、东北狩野）：已可走 generic_iiif，按需补专属识别
- Phase 4 中国大陆自定义 API 站（天一阁/广州大典/CUHK… 本环境可验证，最贴近索引录入）

## 参考
- CText / 识典 search/match 模板：`bookget/adapters/other/{ctext,shidianguji}.py`
- 共享匹配模块：`bookget/shared/cjk_match.py`
- 搜索模型：`bookget/models/search.py`

---

# 发布相关（后续）

1. bookget-ui（npm 包）
位置：bookget-py/ui/

发布到：npm registry（npmjs.com）


cd bookget-py/ui
npm run build:lib        # 生成 dist/index.js + dist/index.cjs + dist/bookget-ui.css
npm publish              # 发布到 npm
发布后其他项目可以：


npm install bookget-ui
目前 guji-platform 用的是本地 file:../bookget-py/ui，发布后可改为 "bookget-ui": "^0.1.0"。

2. bookget（Python 包）
位置：bookget-py/

发布到：PyPI（pypi.org）


cd bookget-py
pip install build twine
python -m build           # 生成 dist/bookget-0.x.x.tar.gz + .whl
twine upload dist/*       # 上传到 PyPI
发布后：


pip install bookget
python -m bookget download <url>
python -m bookget serve      # 启动 Web UI
3. VS Code 扩展（guji-platform）z
位置：guji-platform/

发布到：VS Code Marketplace 或直接分发 .vsix 文件


cd guji-platform
npm install -g @vscode/vsce
vsce package              # 生成 guji-platform-0.x.x.vsix
vsce publish              # 发布到 Marketplace（需要 PAT token）
直接安装 vsix：


code --install-extension guji-platform-0.x.x.vsix
4. 可执行文件（exe，Phase 5 待实现）
发布到：GitHub Releases（附件形式）

文件	内容
bookget-cli.exe	PyInstaller 打包 bookget CLI，无 UI
bookget-ui.exe	PyInstaller 打包 server + ui/dist-app/ 静态文件，启动后自动打开浏览器

# bookget-cli
pyinstaller --onefile --name bookget-cli bookget/__main__.py

# bookget-ui（需要把 dist-app/ 一起打包）
pyinstaller --onefile --name bookget-ui \
  --add-data "ui/dist-app:ui/dist-app" \
  bookget/server/__main__.py