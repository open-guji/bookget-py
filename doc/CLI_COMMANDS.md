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
| 台湾 NPM (故宫博物院) | ✓ | — | — | — | — | — |
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
