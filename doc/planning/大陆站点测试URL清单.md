# 大陆站点测试 URL 清单（来自 bookget wiki + 实测）

> **自 overview `项目进展/资源下载/` 迁入（状态为 2026-09 前的实测）。** 仅作大陆站点冒烟/live 测试的 URL 备忘；已入 `site_urls.yaml` / `live_urls.yaml` 的以仓内为准。


> 用途：Phase 4 大陆站 / 登录-反爬阶段的测试 URL 库。
> 来源：bookget wiki [04.可用的网站URL](https://github.com/deweizhu/bookget/wiki/04.%E5%8F%AF%E7%94%A8%E7%9A%84%E7%BD%91%E7%AB%99URL) 的示例 URL（确认 wiki 每站都给了 item 级示例）。
> 状态来自本沙箱（美区）chrome-mcp 实测；⚠️ 美区沙箱多有地域/登录限制，**最终 live 验证建议在可达环境（GCP dev-vm / 本机）跑**。

## 已实测

| 站点 | 示例 URL | 沙箱可达 | 备注 |
|---|---|:--:|---|
| 广州大典 | `https://gzdd.gzlib.org.cn/website/gzddDatabase/articleDetails?id=GZDD034603002`（详情）<br>`…/articleFulltext?id=GZDD034603002`（阅读） | ✅ | Vue SPA。`api/Search/Detail?id=` 出元数据（**免登录**，含 Title/Responsibility/Edition/Pages/CollectionUnits/PdfPath）；但 `api/Search/ReadBook?id=`（页图）返回 `{"Code":401,"认证失效"}` —— **需 Bearer token + fingerprint（登录）**。→ 登录阶段做 |

## 待测（wiki 示例 URL，未在沙箱实测 / 预计 geo 或登录受限）

| 站点 | 示例 URL（wiki） | 预判 |
|---|---|---|
| 国图·读者云门户 read.nlc.cn | `http://read.nlc.cn/allSearch/searchDetail?searchType=1002&showType=1&indexName=data_892&fid=411999021002`<br>`http://read.nlc.cn/OutOpenBook/OpenObjectBook?aid=892&bid=96323.0` | 已有 nlc_read 适配器；geo 限制 |
| 深圳市古籍 | `https://yun.szlib.org.cn/stgj2021/srchshowbook?type=4&book_id=18269` | 需微信小程序登录 |
| 洛阳市图书馆 | `http://111.7.82.29:8090/productshow.php?cid=4&id=112` | IP 直连，疑 geo |
| 温州市图书馆 | `https://oyjy.wzlib.cn/resource/?id=62c6c1b0417eaa3687cb08bf`<br>`https://arcgxhpv7cw0.db.wzlib.cn/detail.html?id=200738&isTopic=1` | 两套平台 |
| 云南数字方志馆 | `http://dfz.yn.gov.cn/record/pdf?id=old060001` | .gov.cn，PDF，疑 geo |
| 江苏高校珍贵古籍 | `https://jsgxgj.nju.edu.cn/#/resource/bookdetails?bookId=GJ-1668922900001` | SPA |
| 诸城市图书馆 | `http://124.134.220.209:8100/index.php?ac=detail&id=400757` | IP 直连，疑 geo |
| 中央美院图书馆 | `http://dlib.cafa.edu.cn/ebook/item/7294-n-a?offset=1` | |
| 中华寻根网（家谱） | `http://ouroots.nlc.cn/view.html?41510488-2-1-1` | |
| 抗日战争与近代中日关系 | `https://www.modernhistory.org.cn/#/DocumentDetails_qk?fileCode=9999_qk_00005` | SPA |

## 实施建议
- **登录类**（广州大典/深圳/ncpssd…）：登录阶段统一做 cookie/token 注入后再接 ReadBook 类接口。
- **疑 geo 类**（read.nlc.cn / dfz.yn.gov.cn / IP 直连）：在 GCP dev-vm（或本机）跑 chrome-mcp 抓接口 + `pytest -m live` 验证。
- 流程同已验证站点：chrome-mcp 抓真实 API → 写适配器 → 登记 `site_urls.yaml`（离线路由守卫）+ `live_urls.yaml`（真连，在可达环境跑）。
