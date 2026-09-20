# 下一个版本（v0.5.0）盘点：功能缺口与站点对齐

> 2026-09-20 实测盘点。目标：**发布时功能尽量完整**，并向上游
> deweizhu/bookget（Go，1779 star）的站点覆盖对齐。
> 数据来源：上游 `router/interface.go` 的域名路由表（74 个域名）+
> 本仓运行期 `AdapterRegistry`，非文档转述。

## A. 站点覆盖：按**域名**比对（决定用户的 URL 能不能用）

| | 数 |
|---|---|
| 上游路由的域名 | **74** |
| 我们能路由 | **29** |
| **路由不了** | **45** |
| 我们有、上游没有 | 11（ctext / 识典 / 维基文库 / 维基共享 / 漢籍 / 梵蒂冈 / 剑桥 CUDL / BnF / 斯坦福 / 台北故宫 / generic_iiif）|

> 注意：不是「37 vs 58」这么简单——同一个站上游常路由多个域名
> （如 IDP 有 7 个镜像域、NLC 有 4 个子站），按域名算才反映真实可用性。

### A1. 中国大陆（17 个域名缺失）— **优先级最高**
最贴近古籍索引录入，且本机网络可直接验证。
- 天一阁 `gj.tianyige.com.cn`
- 广州大典 `gzdd.gzlib.gov.cn` / `gzdd.gzlib.org.cn`（**需登录态**，旧档已记）
- 深圳 `yun.szlib.org.cn`、山东 `guji.sdlib.com`、甘肃 `zszy.gslib.com.cn`
- 温州 `oyjy.wzlib.cn` / `arcgxhpv7cw0.db.wzlib.cn`
- 山东中医药大学 `gjsztsg.sdutcm.edu.cn`、南京大学 `jsgxgj.nju.edu.cn`
- 中央美院 `dlib.cafa.edu.cn` / `dlibgate.cafa.edu.cn`
- 云南方志 `dfz.yn.gov.cn`、近代史 `www.modernhistory.org.cn`
- 国家哲社 `www.ncpssd.cn` / `.org`
- **NLC 其余子站**：`mylib.nlc.cn`、`ouroots.nlc.cn`、`idp.nlc.cn`
  （我们只做了 `guji.nlc.cn` 与 `read.nlc.cn`）

### A2. 日本（9）
早稻田 `archive.wul.waseda.ac.jp`（旧档记为 grind，需逐页探）、
东大东文研 `shanben.ioc.u-tokyo.ac.jp`、宫内厅/庆应 `db2.sido.keio.ac.jp`、
京大人文研 `kanji.zinbun.kyoto-u.ac.jp`、駒澤 `repo.komazawa-u.ac.jp`、
关西大 `www.iiif.ku-orcas.kansai-u.ac.jp`、国立公文書館
`www.digital.archives.go.jp`、米沢 `www.library.yonezawa.yamagata.jp`、
龙谷 IDP `idp.afc.ryukoku.ac.jp`

### A3. 韩国（4）· 港台（1）· 越南（1）· 俄罗斯（2）
奎章阁 `kyudb.snu.ac.kr`、高丽大 `kostma.korea.ac.kr` / `idp.korea.ac.kr`、
韩国国立中央图书馆 `lod.nl.go.kr`；香港中文 `repository.lib.cuhk.edu.hk`
（**WAF 全拦**，旧档已记）；越南汉喃 `hannom.nlv.gov.vn`；
俄罗斯国立图书馆 `viewer.rsl.ru`、`idp.orientalstudies.ru`

### A4. 欧美/其他（11）
**IDP 国际敦煌项目**是个大头：上游路由 7 个镜像域
（`idp.bl.uk` / `idp.bnf.fr` / `idp.bbaw.de` / `idp.nlc.cn` /
`idp.korea.ac.kr` / `idp.afc.ryukoku.ac.jp` / `idp.orientalstudies.ru`），
做一个适配器即可全覆盖，**性价比最高**。
其余：HathiTrust `babel.hathitrust.org`、FamilySearch（需登录）、
史密森 `asia.si.edu` / `www.si.edu`（我们只做了 `ids.si.edu`）、
普林斯顿 catalog 域、喃遗产 `lib.nomfoundation.org`

## B. 已知不工作 / 未验证（比加新站更该先办）

- [ ] **Berkeley manifest 模板是错的**：`digicoll.lib.berkeley.edu/iiif/{id}/manifest.json`
      返回 HTTP 202 而非 JSON，该适配器**从来没成功过**。
      （2026-09-20 已让报错可读，但模板仍需用 chrome-mcp 抓真实 manifest 反推）
- [ ] **17 个适配器从未做过 live 验证**（`live_urls.yaml` 只登记了 20/37）：
      archive_org、berkeley、bnf_gallica、british_library、generic_iiif、
      hanchi、harvard、hku、kyoto_rmda、ncl_rbook、nlc_guji、nlc_read、
      npm_taipei、princeton、shidianguji、stanford、wikimedia_commons。
      **发布前应逐个拿真实 URL 跑通**——本轮抽查 10 个就有 1 个真 bug
      （Berkeley）、1 个 0 图（archive_org 需确认取图逻辑）。
- [ ] **archive_org 返回 0 图**：需确认是样本问题还是取图逻辑问题
- [ ] **hku / cuhk 网络受限**：hku 用户与沙箱均访问不通；cuhk WAF 全拦

## C. 功能缺口（UI 侧）

UI 只暴露了 discover / download / expand / cancel / delete，
**CLI 有而 UI 没有**：`search`、`match`、`metadata`、
`upload` / `ia-patch` / `ia-check`（IA 上传三件套）。
- [ ] UI 加「搜索」页：`search` + `match` 已有 API（4 个站支持搜索）
- [ ] UI 加「上传到 IA」：三件套已完成，但只能命令行用

## D. 文本能力偏薄
`supports_text` 仅 5 个（ctext / 漢籍 / nlc_guji / 识典 / 维基文库）；
上游多数站点也只做图。若要「文字资源」成为卖点，需单独立项，
不属于 v0.5.0 的对齐目标。

## E. 建议的 v0.5.0 范围（按性价比排序）

1. **先修不工作的**：Berkeley 模板、archive_org 0 图、补齐 17 个 live 验证
2. **IDP 一个适配器吃掉 7 个域名**（敦煌文献，学术价值高）
3. **中国大陆一批**：天一阁、深圳、山东、甘肃、温州、南大、央美
   （本机可直接验证；广州大典需登录态，单列）
4. **NLC 其余子站**：mylib / ouroots / idp（同一机构，可复用会话逻辑）
5. **UI 补 search/match**（后端已就绪，纯前端工作）
6. 日本/韩国余下站点（多为 IIIF，单站成本低，但需真实 item URL）

> **教训（勿忘）**：新增适配器必须同时登记
> `tests/fixtures/site_urls.yaml`（覆盖率守卫会强制）+
> `live_urls.yaml` 并本地 `pytest -m live` 真跑一次。
> 本轮证明「适配器存在」不等于「适配器能用」。

---

# 下发任务（2026-09-19，来源：overview 盘点实测）

> 2026-09-19 实测结论：本项目**代码走在前面、交付落在后面**。
> master 注册 37 个适配器，但最新 release v0.3.4（2026-04-27）只有 19 个。
> 用户拿到的是**四个多月前的版本**，近半年的工作没有任何用户能用到。
> 两个 open issue 都源于此。下一步以「把已有成果交付出去」为主线，而非继续加站点。

## 实测到的事实（与上次盘点不同之处）

| 项 | 实测值 | 说明 |
|---|---|---|
| master 适配器数 | **37** | `AdapterRegistry.list_adapters()` 运行期实测 |
| v0.3.4 适配器数 | **19** | v0.3.4 worktree 同法实测 → **18 个未交付** |
| 未发布提交 | 3 个（含「20+ 适配器」大提交） | `git log v0.3.4..master` |
| 离线测试 | **489 passed / 3 failed** | 非旧档所记「全绿」 |
| 未提交工作 | IA 上传三件套（270 行新文件 + 6 文件改动） | 只在本地工作区，**未 commit 未推送** |
| 当前分支 | `master`（非 main） | 与其他仓不一致 |

---

## 2026-09-19 本轮已办（实测结论，替代上方部分推断）

> 上方「实测到的事实」里对 issue #1 的猜测（headless 矛盾）**是错的**，
> 已按实测订正，保留原文以便对照推断与真相的差距。

- **issue #1 真正的病因不是 headless**，而是站点把段落接口 v2 升到 **v3**，
  适配器硬匹配 "paragraphs/v2" 导致拦截不再触发：日志「999 paragraphs」
  却「Collected 0」，最后还报成功。headless=True 实测三条路径全部正常。
  顺带修掉另两个真缺陷：
  - 图片翻页用 ArrowRight（翻的是文字栏，图片不加载）→ 改滚动阅读器容器，
    签名 URL 2/36 → **35**
  - 签名 CDN 链接 403：aiohttp 把 x-signature 里的 %2F 规范化成 `/`
    → 改 yarl.URL(encoded=True)，**35/35 零失败**
- **OpenCC 未声明依赖**确认为 3 个失败测试的根因；另发现 `_get_variant_map`
  读 `<pkg>/dictionary/*.txt`，而新版 wheel 只发二进制 .ocd2，
  **即使装了 OpenCC 异体表也恒为空**（徴 归一不到 徵）→ 改用
  jp2t/tw2t/hk2t 构建，异体表 0 → **406 条**
- **另外发现并修复**（不在原计划内）：
  - 仓库根本没有 LICENSE 文件，pyproject 指向不存在的文件，构建告警、
    PyPI 包不含许可证、GitHub 认不出。已补 **Apache-2.0**（与
    book-index-manager 一致），并改用 PEP 639 写法
  - `dev` extra 缺 pytest-asyncio，全新 `pip install -e ".[dev]"`
    连测试都收集不起来
  - CText 书籍 ID 形如 `path:analects`，`:` 在 Windows 非法 →
    批量下载落盘前统一过 `_safe_dirname()`
  - `bookget/__init__.py` 的 `__version__` 停在 0.1.0，与 pyproject 脱节
- 离线套件 **489 passed / 3 failed → 511 passed / 0 failed**

### 尚未做（交给下一轮）
- **推送 + 打 tag v0.4.0**：本轮所有提交仍在本地 master，未 push
  （用户要先自己过目；tag 会触发 PyPI + GitHub Release）
- `master` → `main` 改名（P2，唯一剩下的 P2 项）
- `[tiles]` 的 Pillow 仍是惰性 import，缺失时行为待统一
- nlc_guji：册名（volumeTitle）在 get_image_list 里拿到却传不下去，
  因 Resource 无 title 字段；要带下去需加模型字段，已在代码里注明现状

### 2026-09-19 第三轮：exe 实测（发布前把关）
真把 bookget-cli.exe / bookget-ui.exe 构建出来逐项跑，修掉三个只在打包环境
暴露的问题：
- **两个 spec 都把 PIL 放进 excludes**，而 tiles.py 需要它拼 Zoomify 瓦片
  → exe 里必然缺 Pillow，开发环境却正常（典型「只在发布版坏」）
- **opencc 未进 hiddenimports**（本轮刚升为正式依赖）
- **瓦片站在普通 download 路径上全军覆没**：TNM 的 Resource.url 是瓦片基址，
  裸 GET 必 404；拼接只写在 download_node 里，而它只有 --incremental 会调用。
  适配器加 fetch_resource()，ResourceManager 有则用之。0/140 → 133 张
  （5760×3840，PIL 校验全有效）。
  **坑**：探测 fetch_resource 要查**类**不能查实例——Mock 适配器对任何属性名
  都返回 mock，按实例探测会把真实下载导进不可 await 的桩（既有测试当场抓到）
- 另修 CText 标题未做 HTML 实体反转义（三处只有一处 unescape）
- **CI 只装 `[dev]`**，Pillow 根本不在构建环境里，光改 spec 没用 → 改
  `[dev,tiles]`，并新增 `bookget selftest` + release.yml 构建后冒烟，
  构建坏了直接发不出去。故意把 PIL 写回 excludes 验证过这道闸拦得住
  （体积 19.9MB→13.8MB，PyInstaller 仍报成功，selftest 退出码 1）

exe 实测通过：37 适配器、OpenCC、CText 元数据、批量下载、梵蒂冈 IIIF
162/162 零失败、TNM 瓦片 133 张、UI exe 前端与 API 均 200 且真下完 163 个
文件、识典在 exe 给中文指引。测试 517 → **523 passed**。

### 2026-09-19 第二轮追加（P2 已清）
- 版权归属改为 **开源古籍 (open-guji)**，不写个人名（LICENSE + pyproject authors）
- **PDF-only 站点不再被 discover 跳过**：`discover` 只看 supports_images，
  而 nlc_read 声明 images=False/pdf=True 且 PDF 也从 get_image_list 返回
  → manifest 恒为空。改为 `supports_images or supports_pdf`，
  server 能力上报补 supports_pdf，README 加 PDF 列（整表全部取自代码声明）
- **ruff 从「约 700 条无人看」变成全绿**：加 [tool.ruff] 收敛到 pyflakes +
  真错类规则，--fix 清 447 条未用 import，手工删 6 处死变量
- **CJK_VARIANTS 有重复键**（F601）：`'餘'` 出现两次，后者静默覆盖前者。
  实测三形仍两两匹配故无线上影响；已删重复并加 AST 守卫测试
- 测试 511 → **517 passed**

---

## P0 — 止血：把已完成的东西交出去

### [x] 0.1 先落盘未提交的 IA 上传功能（done 2026-09-19，commit f484e5f）
`bookget/ia_upload.py`、`bookget/ia_metadata.py` 两个新文件**从未 commit**，
外加 main.py / cli.spec / ui.spec / pyproject / CLAUDE.md / DEVELOPER.md 六处改动挂在工作区。
这是**丢失风险最高的一项**——一次误 clean/stash 就没了。
- 先 `pytest` 确认不破坏现有套件，再单独 commit 推上去
- 注意 `[ia]` extra 已加进 pyproject，属同一批改动，一起提交

### [x] 0.2 修 cjk_match 的 3 个失败（done 2026-09-19，commit 102ca69）
```
FAILED test_simplified_matches_traditional   论语 ↔ 論語 不匹配
FAILED test_traditional_matches_simplified
FAILED test_simplified_traditional（作者）
```
**根因：`bookget/shared/cjk_match.py` 依赖 OpenCC，但 `pyproject.toml` 里
dependencies 和所有 extra 都没声明它。** 代码写了「OpenCC 缺失时优雅降级」，
于是 pip 装的用户繁简匹配**静默失效、不报错**——search/match 少一半结果而无人知道。
- 把 `opencc` 加进正式 `dependencies`（这是核心能力，不该是可选）
- 或明确降级为 extra，但需在 search/match 路径给出显式 WARNING，不能静默
- 修完三个测试应转绿；**不要改测试去迁就代码**

### [~] 0.3 发 v0.4.0，把 18 个适配器交付给用户（**只差一条 tag 命令，需本人执行**）
这是对两个 issue 最直接的回应。
- [x] 确认 release.yml 仍可跑：2026-09-20 用 workflow_dispatch 空跑 run #9，
      **三平台全绿**（构建 + selftest 冒烟 + 适配器计数 ≥37 + 批量下载 flag）。
      `pypi` / `release` 两个 job 按 `if: startsWith(github.ref, 'refs/tags/')`
      正确 skip——手动触发不会误发布，这条空跑以后每次发版前都该做
- [x] README 站点表已是 37 站（旧记录说「需从 19 更新」已过时）
- [x] PyPI 侧已确认：`bookget` 项目存在（最新 0.3.4），Trusted Publisher 此前
      跑通过，0.4.0 未被占用
- [ ] **打 tag 推送——沙箱做不了**：Claude 会话的 git 凭据只允许推指定的
      `claude/*` 分支，推 tag ref 恒返回 **HTTP 403**（退避重试 5 次全同）；
      代理 `recentRelayFailures` 为空，不是出网策略。GitHub MCP 也没有建
      tag / 建 Release 的接口。**需本人在本地执行**：
      ```bash
      git fetch origin main
      git tag -a v0.4.0 origin/main -m "v0.4.0"
      git push origin v0.4.0      # 只推 tag，不动分支
      ```
- [ ] 发版后在 issue #1 / #2 下回复，告知新版本

---

## P1 — 回应 issue

### [x] 1.1 issue #1「识典古籍下载失效」（done 2026-09-19，commit 9acaaa3）
实测：站点活着（book 页 200），但 `/api/ancientlib/read/reader-book/get/{id}`
裸请求返回 `{"errorCode":40001}`——鉴权仍在，Playwright 路线**仍然必要**
（SSR `_ROUTER_DATA` 只有壳、无正文，没有免浏览器捷径）。

**已定位一处强嫌疑 bug：代码与自身注释矛盾。**
`shidianguji.py:87-88` 注释写：
> Uses headless=False because 识典古籍's ByteDance SecSDK detects
> headless browsers, causing unstable API responses.

但第 96 行和第 133 行实际都是 `headless=True`。对照 `ncl_rbook.py:338` 用的是
`headless=False`。该矛盾自 v0.2.0 即存在（`git log -L` 确认），属长期潜伏 bug，
与「时好时坏/突然失效」的症状吻合。
- 先装 playwright 复现（本机当前**未装**，无法直接验证，这是必须先做的一步）
- 按注释改回 `headless=False`（窗口移出屏外），或改为可配置并默认 false
- 另需排查：exe 用户根本没有 playwright——`cli.spec`/`ui.spec` 里
  **没有任何 playwright/chromium 打包痕迹**，下载 exe 的用户用识典必然失败。
  至少要在 exe 里给出清晰的中文提示而非堆栈
- 修完回复 issue #1

### [x] 1.2 issue #2「支持批量下载吗」（done 2026-09-19，commit 34b2b95）
实测：`download` 子命令只接受**单个 url**（`p_download.add_argument("url")`），
确无批量能力。已在 issue 下回复「暂时更新较少、欢迎共建」，但功能本身值得做，
且成本不高（基础设施齐全：已有 `--concurrency`、`--incremental`、
`.download_state.json` 断点续传）。
建议最小实现：
- `download` 支持多个 url 位置参数，及 `--url-file <f>`（每行一个 URL，`#` 注释）
- 复用现有并发与续传；单条失败不中断整批，末尾打印汇总（成功/失败/跳过）
- 失败清单落盘，支持 `--retry-failed` 重跑
- 加离线测试；完成后回复 issue #2

---

## P2 — 卫生与一致性

- [x] 分支名 `master` → `main`（已完成：远端只剩 `main`；本档上方多处仍写 `master`，
      `.claude/commands/release.md` 也一并改过来了）
- [x] 本档旧记录里多处「离线 XXX passed 全绿」已不准（实测 3 failed）
      → 已修，当前 **517 passed / 0 failed**；引用测试数请以实跑为准
- [x] extra 缺失依赖的「静默降级」→ 已处理：OpenCC 升为正式依赖且缺失时告警；
      识典缺 Playwright 时给中文指引（exe 环境单独措辞）。
      `[tiles]` 的 Pillow 仍是惰性 import，待同样处理

---

## 暂缓（理由）

**继续加新站点适配器暂缓。** 站点覆盖已 37 个、抓取能力不是瓶颈；
而已做好的 18 个站点用户根本拿不到。先把交付链路打通（P0），
再谈广度。旧档 Phase 3 尾部的待办站点（宫内厅/东大东文研/国立公文书馆/
奎章阁/俄国 RSL/IDP、早稻田 grind、广州大典登录态）原样保留在下方，
不删除，待 P0/P1 清完再评估。

---
# 下发任务（2026-09-08，来源：overview `项目进展/资源下载/todo.md` P1）

> 2026-09-08 按：盘点时误以为本档为空，实测本档内容完整（下方原有大量记录）。
> 按原计划把 资源下载/todo.md 的 P1 三条摘要下发于此，注明来源与日期。

- [ ] **1.3 文本质量抽样**：ctext（API）/ 维基文库（API/dump）/ 识典（Playwright）/ 漢籍
      的章节层级、夹注、Markdown 输出抽样，需联网 QA
- [ ] **nlc_read / ncl_rbook 深字段需实样补齐**：nlc_read 详情页深度字段（作者/年代）需
      read.nlc.cn 实样（IP 受限）；ncl_rbook 更多书志字段需 rbook 实样（滑块验证）
- [ ] **中央研究院明实录**：漢籍 hanchi 适配器已支持文本，明实录浏览路径待确认

P0（资源覆盖率匹配）已在本档下方 Phase 1-4 的既有工作中体现（抓取能力已非瓶颈，
瓶颈在匹配），此处不重复列出，避免与下方原有记录冲突。

---

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