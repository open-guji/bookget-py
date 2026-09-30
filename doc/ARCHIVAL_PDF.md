# 归档 PDF 指南：从故宫 Open Data 到可上传的 PDF

本文说明如何用 bookget 把国立故宫博物院 Open Data 的书画作品下载为原始分辨率影像，并合成带完整元数据与「文物資料表」的归档 PDF——即已上传维基共享资源的《法帖》《法書》《拓片》批次（约 3,900 件）所用的格式。同样的 `pdf` 命令也适用于 bookget 其它站点的下载目录。

命令参数的完整列表见 [CLI_COMMANDS.md](CLI_COMMANDS.md)；站点结构与 API 见 [臺灣故宮博物院 Open Data](websites/臺灣故宮博物院%20Open%20Data.md)。

## 1. 安装

```bash
pip install bookget[pdf]          # Pillow（资料表栅格化）+ PyMuPDF（结果校验）
```

PDF 写入本身不依赖第三方库。要生成与维基共享资源批次相同的排版版式，还需要：

| 组件 | 说明 |
|------|------|
| TeX Live（含 LuaLaTeX） | `lualatex` 在 PATH 上，或位于 `~/texlive/<年份>/bin/<平台>/`、`/usr/local/texlive/...`；也可用环境变量 `BOOKGET_LUALATEX` 指定路径 |
| LaTeX 宏包 | fontspec、luatexja、geometry、xcolor、longtable、tabularx、xurl、embedfile、hyperref、hyperxmp、bookmark（TeX Live 完整安装均已包含） |
| CJK 字体 | 默认依次查找 Source Han Serif TC/SC、Noto Serif CJK、Fandol、TW-Kai；用 `BOOKGET_CJK_FONT` 指定 TeX Live 能找到的字体文件名 |
| 西文字体 | TeX Gyre Pagella、Latin Modern（TeX Live 自带） |

没有 TeX Live 时使用默认的 `native` 引擎：内容相同，资料表由 Pillow 栅格化为图片页（系统无 CJK 字体时跳过资料表，但 PDF 仍带全部元数据与附件）。

## 2. 快速开始

### 单条记录

```bash
bookget download "https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=1528&dep=P&mode=full" -o ./npm/P1528 --pdf
```

任何一种详情页 / IIIF 检视器 URL 都可以（`Pub/Detail?id=…&dep=P`、`Pub/Detail/1528?dep=P`、`Pub/DetailEng/…`、`Collection/Detail?id=…&dep=U`、`IIIFViewer?id=…`）。

### 整件作品（冊页 / 卷）

故宫把冊页的每一开做成独立记录。加 `--album` 后，bookget 以「文物統一編號」前缀（如 `故帖000156`）在站内检索出全部开页记录，按影像编号前缀（`K2D000156`）归为一件作品，下载全部影像（去重、按编号排序），并把每条记录的解析结果写入 `raw.npm_taipei.json`：

```bash
bookget download "https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=16797&dep=P&mode=full" \
    -o ./npm/gutie000156 --album --pdf --pdf-engine latex
```

给出冊中任意一开的 URL 即可，结果相同。

### 整个分类批量

```bash
# 1. 列出分类（分类名：繪畫 / 法書 / 法帖 / 拓片 / 成扇 / 其他），每页最多 500 条
bookget search npm_taipei "category:法帖" --limit 500 --json > fatie_p1.json
bookget search npm_taipei "category:法帖" --limit 500 --offset 500 --json > fatie_p2.json

# 2. 生成 URL 列表（可在此按品名过滤，见第 6 节）
python3 - <<'PY' > urls.txt
import json, glob
for f in sorted(glob.glob("fatie_p*.json")):
    for r in json.load(open(f))["results"]:
        if not r["title"].startswith(("民國", "現代", "當代")):
            print(r["url"])
PY

# 3. 批量下载：每本一个子目录，失败的 URL 写入 failed_urls.txt，可用 --retry-failed 重跑
bookget download --url-file urls.txt -o ./fatie --album --pdf --pdf-engine latex
```

同一冊的各开 URL 会各自展开成同一件作品；如需去重，先按检索结果的品名（去掉最后一段开页名）合并，或在下载后按 `pdf/` 文件名去重。

### 对已下载目录合成 / 重新合成

```bash
bookget pdf ./npm/gutie000156 --engine latex          # 单本
bookget pdf ./fatie --engine latex                    # 批量：每个含 images/ 的子目录各一份
bookget pdf ./npm/P1528 --reverse -o ./out/x.pdf      # 页序反转、指定输出
bookget pdf ./npm/P1528 --engine latex --keep-build   # 保留 build/doc.tex、doc.log 排查排版问题
```

## 3. 目录与文件

```
<book_dir>/
├── metadata.json           BookMetadata：题名、作者、朝代、分类、統一編號、授权、来源 URL …
├── raw.npm_taipei.json     站点解析结果：单记录 = 各分页字段/表格（中英文）；整件 = 每条记录 + 影像归属
├── images/
│   ├── 001_K2D000156N000000001PAA.jpg   IIIF full/full 原始文件（不重编码）
│   └── …
└── pdf/
    └── NPM-故帖000156_宋榻大觀帖_九_冊.pdf
```

**文件名**：`<前缀>-<統一編號>_<品名>.pdf`。冊级后缀 `N000000000` 去掉，单开的 `N000000012` 保留；品名去掉英文尾巴，空白与括号换成 `_`。例如整冊 `NPM-故帖000156_宋榻大觀帖_九_冊.pdf`，单开 `NPM-故帖000156N000000012_宋榻大觀帖_九_冊_晉王獻之吳興帖.pdf`。前缀默认 `NPM`（其它站点为站点 id 大写），可用 `--name-prefix` 改。

## 4. PDF 里有什么

| 内容 | 说明 |
|------|------|
| 影像页 | 每幅按像素尺寸（默认 300 dpi 换算）单独成页，JPEG 数据原样嵌入 |
| Info 字典 | Title / Author / Subject / Keywords / Creator，以及自定义键：ObjectNumber（或 ObjectNumberPrefix、ObjectNumbers、OpenDataIDs）、Category、Script、Holder、License、Attribution、IIIFManifest、ImageIDs、Retrieved 等 |
| XMP | Dublin Core（题名、作者、主题、出版者、来源、权利声明）、xmpRights 授权 URL；latex 引擎由 hyperxmp 写入 |
| 书签 | 单记录：每幅一条；整件：每开第一幅一条（`故帖000156N000000012  宋榻大觀帖（九） 冊 晉王獻之吳興帖`），末尾「文物資料表」 |
| 页码标签 | 影像页 = 影像编号；资料表页 = 罗马数字 |
| 附件 | `metadata.json`、`raw.npm_taipei.json` 嵌入 PDF（可从 PDF 恢复全部元数据） |
| 文物資料表 | 基本資料（總記錄）、典藏尺寸、質地、題跋、印記、開頁記錄、釋文（各記錄）、印記／題跋／尺寸（各記錄）、授權與引用、數位影像、影像清單、來源與製作（含製作工具 bookget-py 链接） |

两种引擎：

| | `--engine native`（默认） | `--engine latex` |
|---|---|---|
| 资料表 | Pillow 渲染成 JPEG 页；无 CJK 字体则省略 | LuaLaTeX 排版，文字可选取、可检索，方框表单版式 |
| 依赖 | 无（资料表需 Pillow） | TeX Live + CJK 字体 |
| 速度 | 快 | 每本数秒到数十秒 |
| 用途 | 快速归档、无 TeX 环境 | 维基共享资源等对外发布 |

## 5. 校验

装有 PyMuPDF 时，每次合成后自动检查：影像页与 `images/` 文件逐字节一致且顺序正确；没有空白页（LaTeX 排版失败的典型症状）。不通过则报错并退出码 1。`--no-verify` 可跳过。

## 6. 上传维基共享资源前的注意事项

这些是发布策略，bookget 不自动执行：

- **版权**：故宫的 CC BY 4.0 只覆盖影像文件，原作须在来源地与美国均为公有领域。品名以「民國」「現代」「當代」开头的作品，以及作者卒于 1945 年后的作品，之前批次一律不上传。
- **授权模板**：`{{Licensed-PD-Art|PD-old-100-expired|cc-by-4.0|attribution=<资料表「姓名標示（中）」字串>}}`。
- **分类惯例**：每件作品一个以作品名为名的分类（如 `Category:快雪堂帖`），同一丛帖各冊共用；再加分类 `National Palace Museum` 系列的统计分类。
- **重复**：同一統一編號可能同时出现在两个分类（如法帖与法書），上传前按編號去重。

维基文本与结构化数据的生成脚本不在 bookget 内。

## 7. 常见问题

| 现象 | 原因与处理 |
|------|------------|
| `lualatex not found` | 未安装 TeX Live 或不在 PATH：设置 `BOOKGET_LUALATEX=/path/to/lualatex`，或改用 native 引擎 |
| `none of these fonts is installed` | TeX Live 内没有思源宋体等：安装 `tlmgr install sourcehanserif`（或系统字体后 `luaotfload-tool -u`），或 `BOOKGET_CJK_FONT=<字体文件名>` |
| 资料表被跳过（native） | 系统找不到 CJK 字体：`BOOKGET_CJK_FONT=/path/to/font.otf` |
| `Missing character` 警告 | 字体缺字（多为罕见字或私用区字）；latex 引擎会把已知的私用区合字（如 㮮）自动替换 |
| 某记录 manifest 为空 | 站点约 1,200 条记录 GetJson 返回空内容，bookget 自动改用详情页图库的影像编号 |
| Python SSL 证书错误 | 影像主机证书缺 Subject Key Identifier，bookget 已关闭该严格校验；用 curl 手工下载亦可 |
| 整件作品缺少某几开 | 该开无独立影像（多开共用一幅），属正常；「開頁記錄」表列出全部记录 |
| 校验报空白页 | 保留 `--keep-build` 查看 `doc.log`；通常是版面异常高的表格行，请回报 |
