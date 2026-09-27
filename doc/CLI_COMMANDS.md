# Bookget CLI 命令参考

## 快速开始

```bash
# 安装后直接使用
bookget --help

# 或以模块方式运行
python -m bookget --help

# 无参数启动进入交互模式（引导式下载）
bookget
```

---

## 命令总览

| 命令 | 说明 |
|------|------|
| `download` | 下载资源（图片/文字/元数据） |
| `discover` | 探索书目结构，生成 manifest 树 |
| `expand` | 展开已有 manifest 中的某个节点 |
| `metadata` | 仅获取书目元数据 |
| `pdf` | 将已下载的书目目录合成为归档 PDF |
| `search` | 在指定站点搜索书目（关键词模糊搜索） |
| `match` | 精确匹配书名+作者，返回可下载资源链接 |
| `sites` | 列出或检查支持的站点 |
| `serve` | 启动 HTTP 服务器 + Web UI |

---

## download — 下载资源

从 URL 下载古籍的图片、文字和元数据。

```bash
# 基本下载
bookget download "URL" -o ./downloads

# 增量下载（基于 manifest，支持断点续传）
bookget download "URL" -o ./downloads --incremental

# 只下载指定章节
bookget download "URL" -o ./downloads --incremental --section node_id_1 --section node_id_2

# 并行下载（多个节点同时下载）
bookget download "URL" -o ./downloads --incremental --concurrency 3

# 跳过图片，只下载文字
bookget download "URL" -o ./downloads --no-images

# 跳过文字，只下载图片
bookget download "URL" -o ./downloads --no-text

# JSON 格式输出进度和结果
bookget download "URL" --json --json-progress

# 下载完成后合成 PDF（等同随后执行 bookget pdf）
bookget download "URL" -o ./downloads --pdf

# 故宫 Open Data：把冊页/卷的所有開页记录当作一件作品整体下载，并用 LuaLaTeX 生成带资料表的归档 PDF
bookget download "https://digitalarchive.npm.gov.tw/opendata/Pub/Detail?id=16797&dep=P&mode=full" \
    -o ./npm --album --pdf --pdf-engine latex
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `url` | 书目 URL（必填） |
| `-o, --output` | 输出目录 |
| `--no-images` | 跳过图片下载 |
| `--no-text` | 跳过文字下载 |
| `--no-metadata` | 跳过元数据保存 |
| `--incremental` | 使用 manifest 增量下载模式 |
| `--section ID` | 只下载指定节点（可重复使用） |
| `--concurrency N` | 并行下载节点数（默认 1） |
| `--pdf` | 全部图片下载成功后合成 `pdf/<名称>.pdf`（见 `pdf` 命令） |
| `--pdf-engine` | 与 `--pdf` 合用：`native`（默认，纯 Python）或 `latex`（LuaLaTeX 排版资料表，需 TeX Live） |
| `--no-sheet` | 与 `--pdf` 合用：不附元数据资料表（native 引擎） |
| `--no-verify` | 与 `--pdf` 合用：跳过 PyMuPDF 校验 |
| `--album` | 整件作品模式：把该记录所属的整个冊页/卷（所有开页记录）的图片与元数据一起下载（目前支持故宫 Open Data） |
| `--index-id` | 全局索引 ID |
| `--json` | 完成后输出 JSON 结果 |
| `--json-progress` | 输出 JSON 格式进度事件 |
| `-q, --quiet` | 静默模式 |

---

## discover — 探索书目结构

探索书目的层级结构（卷/册/章节），生成 manifest 文件，不下载内容。

```bash
# 探索顶层结构
bookget discover "URL" -o ./output

# 完整深度探索
bookget discover "URL" -o ./output --depth -1

# 输出 JSON 格式
bookget discover "URL" --json
```

| 参数 | 说明 |
|------|------|
| `url` | 书目 URL（必填） |
| `-o, --output` | 输出目录 |
| `--depth N` | 探索深度（-1=完整，1=仅顶层，默认 1） |
| `--json` | 输出 manifest JSON |
| `--json-progress` | 流式输出探索事件 |

---

## expand — 展开 manifest 节点

对已有 manifest 中的某个节点进行更深层的结构展开。

```bash
bookget expand "URL" node_id -o ./output --depth 1
```

| 参数 | 说明 |
|------|------|
| `url` | 书目 URL（必填） |
| `node_id` | 要展开的节点 ID（必填） |
| `-o, --output` | 输出目录（必填） |
| `--depth N` | 展开深度（默认 1） |
| `--json` | 输出 JSON 格式 |

---

## pdf — 合成归档 PDF

完整流程指南（安装、整件作品、整类批量、上传注意事项、常见问题）见 [ARCHIVAL_PDF.md](ARCHIVAL_PDF.md)。

把 `download` 生成的书目目录（`images/` + `metadata.json` [+ `raw.<site>.json`]）合成为一个归档 PDF。JPEG 页面原样嵌入（不重新压缩），PDF 带 Info/XMP 元数据（题名、作者、藏品编号、授权、来源 URL 及自定义键）、每页书签、以图片名作页码标签，并把 `metadata.json`、`raw.<site>.json` 作为附件嵌入，末尾附「文物資料表」（基本资料、开页记录、释文、印记、题跋、尺寸、授权与引用、影像清单、来源与制作）。

两个引擎渲染同一份文档描述（`bookget/pdf/schema.py`）：

| 引擎 | 资料表 | 依赖 |
|------|--------|------|
| `native`（默认） | Pillow 栅格化为图片页（无 CJK 字体时跳过） | 无（资料表需 `pip install bookget[pdf]`） |
| `latex` | LuaLaTeX 排版、可选取文字的表格——即故宫→维基共享资源批量上传所用的版式 | TeX Live（lualatex、fontspec、luatexja、hyperxmp、embedfile 等）+ 思源宋体等 CJK 字体 |

```bash
# 单本（native）
bookget pdf ./downloads/P1528

# LuaLaTeX 排版版
bookget pdf ./downloads/P1528 --engine latex

# 批量目录（每个含 images/ 的子目录各生成一个 PDF）
bookget pdf ./downloads --engine latex

# 不要资料表、页序反转、指定输出文件
bookget pdf ./downloads/P1528 --no-sheet --reverse -o ./out/book.pdf
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `book_dir` | 书目目录或批量目录（可多个） |
| `-o, --output` | 输出文件（仅单本）；默认 `<book_dir>/pdf/<名称>.pdf` |
| `--engine` | `native`（默认）或 `latex` |
| `--no-sheet` | 不附元数据资料表（native 引擎） |
| `--no-verify` | 跳过校验。默认在装有 PyMuPDF 时校验：每页图片与源文件字节一致、顺序正确、无空白页 |
| `--keep-build` | latex：保留 `build/`（doc.tex、doc.log）便于排查 |
| `--reverse` | 页序反转 |
| `--dpi` | 页面尺寸换算用的分辨率（默认 300） |
| `--name-prefix` | 文件名前缀（npm_taipei 默认 `NPM`，其它站点默认站点 id 大写） |
| `--font` | 资料表使用的 CJK 字体文件（也可设环境变量 `BOOKGET_CJK_FONT`） |

文件名规则：有藏品编号时为 `<前缀>-<编号>_<题名>.pdf`（冊级后缀 `N000000000` 去掉，开页的 `N000000012` 保留；题名去掉英文尾巴，空白与括号换成 `_`），如整冊 `NPM-故帖000156_宋榻大觀帖_九_冊.pdf`、单开 `NPM-故帖000156N000000012_宋榻大觀帖_九_冊_晉王獻之吳興帖.pdf`，可直接用于 Wikimedia Commons。环境变量：`BOOKGET_CJK_FONT`（资料表字体文件；latex 引擎下为 TeX Live 内的字体文件名）、`BOOKGET_LUALATEX`（lualatex 路径；默认搜索 PATH 及 `~/texlive/*/bin/*`、`/usr/local/texlive/*/bin/*`）。

**整件作品（`download --album`）**：故宫 Open Data 把冊页的每一开做成独立记录，`--album` 以「文物統一編號」前缀（如 `故帖000156`）在站内检索出全部开页记录，按影像编号前缀（`K2D000156`）归为一件作品，下载全部影像，`metadata.json` 为作品级、`raw.npm_taipei.json` 含每条记录的完整解析结果；随后 `pdf` 生成「總記錄／開頁記錄／釋文（各記錄）／印記資料（各記錄）……」形式的资料表。

---

## metadata — 获取元数据

仅获取书目的元数据信息（书名、作者、朝代、分类等），不下载任何文件。

```bash
# 文本格式输出
bookget metadata "URL"

# JSON 格式输出
bookget metadata "URL" --format json
```

| 参数 | 说明 |
|------|------|
| `url` | 书目 URL（必填） |
| `--format` | 输出格式：`text`（默认）或 `json` |
| `--index-id` | 全局索引 ID |

---

## search — 关键词搜索

在指定站点上搜索书目，返回模糊匹配结果列表。

```bash
# 搜索维基文库
bookget search wikisource "周易"

# 限制结果数量
bookget search wikisource "論語" --limit 10

# 翻页
bookget search wikisource "詩經" --offset 20

# JSON 输出
bookget search wikisource "周易" --json
```

| 参数 | 说明 |
|------|------|
| `site` | 站点 ID，如 `wikisource`（必填） |
| `query` | 搜索关键词（必填） |
| `--limit N` | 最大结果数（默认 20） |
| `--offset N` | 翻页偏移量（默认 0） |
| `--json` | 输出 JSON 格式 |

**目前支持搜索的站点：** Wikisource

---

故宫 Open Data 支持关键词与分类检索（`category:法帖`），单页最多 500 条，可用于整类批量下载：

```bash
bookget search npm_taipei "category:法帖" --limit 500 --json > fatie.json
python3 -c "import json;[print(r['url']) for r in json.load(open('fatie.json'))['results']]" > urls.txt
bookget download --url-file urls.txt -o ./fatie --album --pdf --pdf-engine latex
```

---

## match — 精确匹配书目

根据书名（和可选的作者列表）在指定站点上进行精确匹配，返回可下载资源的链接。与 `search` 的区别在于：

- **search**：关键词模糊搜索，返回搜索结果列表
- **match**：精确书名+作者匹配，返回确认存在的可下载资源链接

`match` 适用于已知书名、需要查找具体下载地址的场景（如批量构建书目索引）。

```bash
# 按书名匹配
bookget match wikisource "周易"

# 带作者匹配（逗号分隔多个作者）
bookget match wikisource "史記" --authors "司馬遷"

# 控制请求间隔（避免触发限流）
bookget match wikisource "論語" --delay 2.0

# JSON 输出
bookget match wikisource "周易" --json
```

**输出示例：**
```
找到 2 个资源:
  - 维基文库: https://zh.wikisource.org/wiki/周易
  - 维基文库（四庫全書本）: https://zh.wikisource.org/wiki/四庫全書/周易
```

| 参数 | 说明 |
|------|------|
| `site` | 站点 ID，如 `wikisource`（必填） |
| `title` | 书名（必填） |
| `--authors` | 逗号分隔的作者列表 |
| `--delay N` | API 请求间隔秒数（默认 1.0） |
| `--json` | 输出 JSON 格式 |

**目前支持匹配的站点：** Wikisource

---

## sites — 站点管理

列出所有支持的站点，或检查某个 URL 是否受支持。

```bash
# 列出所有支持的站点
bookget sites --list

# 检查 URL 是否支持
bookget sites --check "https://ctext.org/analects"

# JSON 输出
bookget sites --list --json
```

---

## serve — 启动 Web 服务

启动本地 HTTP 服务器，提供 Web UI 界面。

```bash
# 默认启动（127.0.0.1:8765，自动打开浏览器）
bookget serve

# 自定义端口
bookget serve --port 9000

# 不自动打开浏览器
bookget serve --no-open
```

---

## 各站点功能支持一览

并非所有站点都支持全部功能，具体能力如下：

| 站点 | 图片 | 文字 | IIIF | PDF | 搜索 | 匹配 |
|------|:----:|:----:|:----:|:---:|:----:|:----:|
| Harvard (哈佛) | ✓ | — | ✓ | — | — | — |
| NDL (日本国会图书馆) | ✓ | — | ✓ | — | — | — |
| Princeton (普林斯顿) | ✓ | — | ✓ | — | — | — |
| Stanford / Berkeley (斯坦福/伯克利) | ✓ | — | ✓ | — | — | — |
| BnF / BL / BSB (法/英/德) | ✓ | — | ✓ | — | — | — |
| 台湾 NCL (国家图书馆) | ✓ | — | ✓ | — | — | — |
| 台湾 NPM (故宫博物院 Open Data) | ✓ | — | ✓ | ✓ (合成) | ✓ | — |
| NLC 古籍 (中国国家图书馆) | ✓ | ✓ | — | — | — | — |
| 识典古籍 (shidianguji) | ✓ | ✓ | — | — | — | — |
| CText (中国哲学书电子化) | ✓ | ✓ | — | — | — | — |
| 汉籍 (Hanchi) | — | ✓ | — | — | — | — |
| Wikisource (维基文库) | — | ✓ | — | — | ✓ | ✓ |
| Archive.org | ✓ | — | — | ✓ | — | — |
| Wikimedia Commons (维基共享资源) | ✓ | — | — | — | ✓ | ✓ |

**说明：**
- `metadata` 和 `download` 命令所有站点都支持
- `search` 和 `match` 目前 Wikisource 和 Wikimedia Commons 已实现
- 下载内容取决于站点能力（有的只有图片，有的只有文字）

---

## 全局选项

```bash
bookget --debug ...     # 启用调试日志
bookget --config FILE   # 指定配置文件路径
```

---

## 按站点示例

### 中华古籍智慧化服务平台 (NLC Guji)

```bash
bookget metadata "https://guji.nlc.cn/guji/pjkf/detail?metadataId=0021001379780000" --format json
bookget download "https://guji.nlc.cn/guji/pjkf/detail?metadataId=0021001379780000" -o ./downloads/nlc
```

### 国立国会図書館 (NDL Japan)

```bash
bookget metadata "https://dl.ndl.go.jp/pid/2592420" --format json
bookget download "https://dl.ndl.go.jp/pid/2592420" -o ./downloads/ndl
```

### 哈佛大学图书馆 (Harvard)

```bash
bookget metadata "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990080724750203941" --format json
bookget download "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990080724750203941" -o ./downloads/harvard
```

### 中国哲学书电子化计划 (CText)

```bash
bookget metadata "https://ctext.org/analects" --format json
bookget download "https://ctext.org/analects" -o ./downloads/ctext
```

### 维基文库 (Wikisource)

```bash
bookget search wikisource "周易"
bookget match wikisource "周易" --json
bookget download "https://zh.wikisource.org/wiki/周易" -o ./downloads/wikisource
```

### Archive.org

```bash
bookget metadata "https://archive.org/details/example" --format json
bookget download "https://archive.org/details/example" -o ./downloads/archive
```
