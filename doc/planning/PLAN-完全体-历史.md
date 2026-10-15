# bookget-py 完全体 · 总计划

> **历史立项文档（2026-05-21，原存于 overview `项目进展/资源下载/`，2026-10 随 overview 拆空迁入本仓）。** 目标与方针决策（纵深优先、登录/反爬站点后置、DRM 平台不做适配器）仍有效；§2「现状基线」已过时（当时约 20 个适配器，现 37 个），最新状态与待办见 [`.claude/todo.md`](../../.claude/todo.md) 与根 README 站点表。


> 创建：2026-05-21　｜　工作流：资源下载　｜　主项目：`D:\workspace\bookget-py`
> 参考：原版 [deweizhu/bookget](https://github.com/deweizhu/bookget)（Go，约 50 真实站点 + 3 通用模式）及其 [Wiki](https://github.com/deweizhu/bookget/wiki)

## 1. 目标（用户需求）

把 bookget-py 做成「完全体」古籍资源下载工具：

1. **尽量支持原版 bookget 现支持的所有图书馆**（约 50 站点）。
2. **额外支持** ctext、识典古籍等（已部分完成）及调研补充的重要资源站。
3. **图片 / 文字 / 元数据 全部提取**。
4. **支持搜索**——只要网站本身支持站内检索。
5. **特殊站点用 Playwright** 取信息/下载（登录、反爬、SPA）。
6. 持续吸收调研出的、原清单遗漏的重要古籍站。

**测试**：统一用 bookget Wiki 的示例 URL（[04.可用网站URL](https://github.com/deweizhu/bookget/wiki/04.%E5%8F%AF%E7%94%A8%E7%9A%84%E7%BD%91%E7%AB%99URL)、[05.IIIF标准网站URL](https://github.com/deweizhu/bookget/wiki/05.IIIF%E6%A0%87%E5%87%86%E7%BD%91%E7%AB%99URL)）建夹具做冒烟测试。

## 2. 现状基线（2026-05-21）

**核心已成熟**（不需重做，是优势）：
- manifest 树 + 增量断点续传下载（discover / expand / download --incremental）
- search / match（书名+作者，繁简异体归一）
- 结构化文本（StructuredText → Markdown / 纯文本）
- aiohttp Web 服务 + React Web UI + 两个 exe（bookget-cli / bookget-ui）打包
- Playwright 已用于：识典古籍、台湾 NCL rbook

**已有约 20 个适配器**（详见 [站点覆盖矩阵-规划.md](站点覆盖矩阵-规划.md)）：
- IIIF：哈佛、普林斯顿、斯坦福、伯克利、京大 RMDA、NDL、通用 IIIF
- 中国：guji.nlc.cn、read.nlc.cn、识典、ctext
- 欧美：Gallica、大英、BSB
- 台湾：NCL rbook、故宫
- 通用：维基文库、维基共享资源、Internet Archive、史语所漢籍

**关键判断**：原版 bookget **只下图片，不做文本/元数据/搜索**。bookget-py 在文本/元数据/搜索/UI 上**已超越** bookget；真正的差距是**图片站点的覆盖广度**（缺约 30 站）。因此本计划 = 「纵深(文/元/搜)继续领先」+ 「广度(图片站)补齐到 bookget」。

## 3. 方针决策（已与用户确认）

| 决策点 | 选择 | 含义 |
|---|---|---|
| 早期优先级 | **纵深优先** | Phase 1-2 先把文本+元数据+搜索做扎实，再铺图片站点广度 |
| 登录/反爬站点 | **后期可选** | FamilySearch 微卷、深圳图书馆微信、ncpssd cookie、HathiTrust 等单列末阶段，不拖慢主线 |
| 商业付费/DRM 库 | **不做下载适配器** | 爱如生系列、雕龙、籍合网、瀚堂、大成等仅登记进 source-catalog 作检索参考（遵循「DRM 平台不作为 resource」原则） |

## 4. 阶段规划

> 纵深优先：Phase 1-2 = 文本/元数据/搜索；Phase 3-5 = 图片站点广度（先 IIIF 易、后自定义 API）；Phase 6 = 登录/反爬可选；Phase 7 = 收尾发布。

### Phase 1 — 文本 / 元数据 / 搜索：核心抽象 + 现有站点打磨
把"三件套"做成一等公民，并在现有 ~20 站点上做扎实。
- **1.1** 抽取繁简/异体字归一化为共享模块（`bookget/shared/cjk_variants.py`，从 `ctext.py` 提取），识典等复用，消除重复。
- **1.2** 统一 `BookMetadata` 覆盖度审计：逐个现有 adapter 补齐 title / author / dynasty / category / collection_unit / version / pages 字段——**元数据是 bookget 完全不做的增量**，要做全。
- **1.3** 现有文本站点质量校验：ctext / 识典 / 漢籍 / 维基文库 的 StructuredText 结构、夹注、章节层级；统一 Markdown / 纯文本输出。
- **1.4** 搜索能力盘点 + 补齐：凡有站内检索 API 的现有站点都实现 `search()` + `match_book()`。**识典 search/match（bookget-py 当前 todo 头号任务）落到此阶段**。
- **1.5** 测试夹具：`tests/fixtures/site_urls.yaml`（取自 bookget Wiki 04/05 示例 URL），对 metadata / search 做冒烟测试。

### Phase 2 — 新增高价值「全文」源
扩充可下载全文来源（bookget 完全没有的能力），优先免费、文本质量高、易抓的：
- **殆知阁** daizhige.org（纯文本，有 GitHub 镜像，底本对照源）
- **CBETA**（佛典，全文 + 可下载 XML/离线版，CC 协议）
- **韩国古典综合DB** db.itkc.or.kr（图文对照，支持中文检索，含韩国文集丛刊）
- **朝鲜王朝实录 / 承政院日记**（sillok / sjw，原文+全文+检索）
- **国学大师** guoxuedashi（全文 + 影印，部分 VIP）
- *(可选)* SAT 大正藏（东大，全文 + IIIF）
每站目标：text + metadata（+ search 若有）。

### Phase 3 — IIIF 图片站点批量补全（广度第一批，最易）
标准 IIIF（v2/v3）：URL→manifest 映射 + 复用现有 IIIF 下载器 + 加 metadata 解析。多数可直接吃 manifest，工作量小、可批量。
- **日本**：kokusho(NIJL)、e国宝、khirin、宫内厅书陵部(keio/sido)、龙谷、关西、庆应、駒澤、东北狩野、大阪府立、东京国立博物馆(ColBase)
- **欧美**：柏林国立、奥地利 ONB、牛津博德利、**剑桥 CUDL**（敦煌/甲骨，调研补充）、**梵蒂冈 DigiVatlib**（调研补充）、Smithsonian
- 同时落地**通用 IIIF 手贴 manifest** 流程（斯坦福 purl、京大、东北狩野等靠用户贴 manifest 的站）。

### Phase 4 — 中国大陆 / 港台 自定义 API 图片站点（广度第二批，中等）
逐站逆向 API（参考 bookget `app/*.go`），每站加 metadata。**这是与古籍索引录入最贴近的一批**（地方志/善本影像）：
- 天一阁、广州大典、温州、洛阳、诸城、云南方志、江苏(njuedu)、中央美院、抗日war1931、甘肃、山东中医、山东古籍、天津、中华寻根(ouroots)、CUHK、USTHK、HKU、台湾华文电子书库
- **DeepZoom 瓦片下载器**（对应 bookget `dzicnlib`）：四川/云南/湖北/江苏省级方志平台共用 `tiles/infos.json` 格式——本阶段实现瓦片拼接引擎（bookget-py 目前缺）。
- 需 cookie 的（深圳 szlib 微信、ncpssd）标注 → 顺延 Phase 6。

### Phase 5 — 海外其它地区 + 敦煌 / 韩国 / 俄 / 越
- 敦煌 IDP（多域名 idp.nlc.cn / idp.bl.uk / …，需先搜关键词取 UID）
- 韩国：奎章阁(kyudb)、高丽大学(kostma)、韩国 LOD/实录(lod.nl.go.kr)
- 日本剩余：早稻田、东洋文库(NII)、国立公文书馆、东大东洋文化研究所、京大人文研、米泽
- 俄国 rslru(viewer.rsl.ru)、越南 hannom.nlv.gov.vn（nomfoundation 视现状确认是否已覆盖）

### Phase 6 —（可选）登录 / 反爬站点
- **统一机制**：cookie.txt / header.txt 注入（对齐 bookget cookiejar）+ Playwright 适配器基类（统一 `_ensure_browser` / `_close_browser` / 复用），把现散落在识典/rbook 的浏览器逻辑收敛。
- 站点：FamilySearch（cookie + 仅微卷）、深圳 szlib（微信小程序登录）、ncpssd（cookie + 运行中刷新）、HathiTrust、书格 shuge（聚合源，提取背后真实馆链接）。
- 商业库：仅登记 source-catalog，不做下载。

### Phase 7 — 收尾：文档 / 测试矩阵 / 发布
- `doc/websites/` 与实际 adapter 对齐；`bookget sites --list` 与矩阵一致。
- 全站点冒烟测试矩阵（CI，用 Phase 1.5 夹具）。
- 发布：PyPI（`bookget`）+ GitHub Release（两个 exe）+ npm（`bookget-ui`）。
- 同步更新 guji-platform 依赖、本 overview 的 projects.md。

## 5. 横切关注点（每个新适配器都要遵守）

- **三件套**：每站尽量同时实现 images + metadata，能拿到就加 text + search。
- **元数据是增量**：bookget 不导出元数据，bookget-py 必须做（这是接入古籍索引的关键）。
- **复用 base 机制**：限流(request_delay)、重试、UA/headers、session 复用。
- **PyInstaller 同步**：新增 adapter 模块要同步 `packaging/cli.spec` + `packaging/ui.spec` 的 `hiddenimports`，否则 exe 报 `No module named`（已知坑）。
- **测试**：每站至少 1 个 bookget Wiki 来源的示例 URL 进夹具。
- **版权**：免费/公有领域优先；DRM/付费库不登记为可下载 resource。

## 6. 里程碑与验收

| 里程碑 | 验收标准 |
|---|---|
| M1（Phase 1-2 完成） | 文本/元数据/搜索三件套抽象稳定；现有站点 + 5 个新全文源均有 metadata+text，可搜的都能搜 |
| M2（Phase 3 完成） | IIIF 站点覆盖追平 bookget 的 IIIF 列表；`sites --list` IIIF 段完整 |
| M3（Phase 4-5 完成） | 中国地方馆 + 海外自定义 API 站点追平 bookget；DeepZoom 瓦片站可下 |
| M4（Phase 7 完成） | 站点数 ≥ bookget；文档/测试矩阵齐全；发布三端 |

## 7. 命令下达方式

本计划批准后，按阶段把**当前阶段任务**写入 `D:\workspace\bookget-py\.claude\todo.md`（项目级命令），`design.md` 记录适配器设计约定。本文件与 [站点覆盖矩阵-规划.md](站点覆盖矩阵-规划.md) 作为工作流总账，随进度更新。

## 8. 关联文档

- [站点覆盖矩阵-规划.md](站点覆盖矩阵-规划.md) — 全站点清单 / 机制 / 当前状态 / 目标能力 / 阶段
- bookget-py 本地：`D:\workspace\bookget-py\doc\websites\`（已有 60+ 站点调研文档，是适配器开发的一手参考）
- bookget-py 项目命令：`D:\workspace\bookget-py\.claude\todo.md`
