# Bookget

古籍数字资源下载工具，支持从 15+ 个数字图书馆网站批量下载古籍图片和文字。

## 支持的网站

### 中国大陆

| 网站 | 域名 | 图片 | 文字 |
|------|------|:----:|:----:|
| 中华古籍智慧化服务平台 | `guji.nlc.cn` | ✓ | ✓ |
| 识典古籍 | `shidianguji.com` | ✓ | ✓ |
| 中国哲学书电子化计划 | `ctext.org` | | ✓ |
| 维基文库 | `zh.wikisource.org` | | ✓ |

### 日本 / 台湾

| 网站 | 域名 | 图片 | 文字 |
|------|------|:----:|:----:|
| 国立国会図書館 (NDL) | `dl.ndl.go.jp` | ✓ | |
| 漢籍全文資料庫 | `hanchi.ihp.sinica.edu.tw` | | ✓ |
| 臺灣國家圖書館 | `rbook.ncl.edu.tw` | ✓ | |
| 臺灣故宮博物院 | `digitalarchive.npm.gov.tw` | ✓ | |

### 欧美图书馆

| 网站 | 域名 | 图片 |
|------|------|:----:|
| 哈佛大学图书馆 | `curiosity.lib.harvard.edu` | ✓ |
| 普林斯顿大学图书馆 | `dpul.princeton.edu` | ✓ |
| 斯坦福大学图书馆 | `searchworks.stanford.edu` | ✓ |
| 柏克莱加州大学东亚图书馆 | `digicoll.lib.berkeley.edu` | ✓ |
| 法国国家图书馆 (BnF) | `gallica.bnf.fr` | ✓ |
| 大英图书馆 | `bl.uk` | ✓ |
| 巴伐利亚州立图书馆 (BSB) | `digitale-sammlungen.de` | ✓ |

### 通用

| 网站 | 域名 | 图片 |
|------|------|:----:|
| Internet Archive | `archive.org` | ✓ |
| 通用 IIIF | 任意 IIIF Manifest URL | ✓ |

## 安装

### 方式一：下载可执行文件（推荐）

前往 [Releases](https://github.com/open-guji/bookget-py/releases) 下载，无需安装 Python：

- **bookget-cli** — 命令行工具，双击运行（Windows / macOS）
- **bookget-ui** — 图形界面，双击打开浏览器操作（Windows / macOS）

### 方式二：pip 安装

需要 Python 3.10 或更高版本。

```bash
pip install bookget
```

如需下载**识典古籍**，还需安装浏览器组件：

```bash
pip install "bookget[browser]"
playwright install chromium
```

## 使用方法

### 图形界面

双击运行 `bookget-ui`，自动打开浏览器，在网页中操作。

或通过命令行启动：

```bash
bookget serve
```

### 交互模式

直接运行 `bookget`（或双击 `bookget-cli`），按提示操作：

```
=======================================================
  bookget — 古籍下载工具
=======================================================

请输入书目 URL（输入 q 退出）: https://www.shidianguji.com/book/v3/1001
  ✓ 已识别站点：识典古籍
下载目录 [C:\Users\xxx\Downloads\bookget]:
并行数量 [3]:

正在探索书目结构……
  标题：周易
  节点：12  已完成：0

开始下载所有节点？[Y/n]:
```

下载完成后会自动回到输入界面，可以继续下载其他古籍。按 `q` 或 `Ctrl+C` 退出。

### 命令行模式

```bash
# 下载古籍
bookget download "URL" -o ./output

# 增量下载（中断后可继续）
bookget download "URL" -o ./output --incremental --concurrency 3

# 只下载图片，不下载文字
bookget download "URL" -o ./output --no-text

# 获取书籍信息
bookget metadata "URL"

# 查看所有支持的网站
bookget sites --list

# 检查某个网址是否支持
bookget sites --check "URL"
```

### 常用选项

| 选项 | 说明 |
|------|------|
| `-o, --output DIR` | 下载保存目录 |
| `--incremental` | 增量下载，支持断点续传 |
| `--concurrency N` | 同时下载数量（默认 1） |
| `--no-images` | 跳过图片 |
| `--no-text` | 跳过文字 |
| `--section NODE_ID` | 只下载指定章节 |
| `-q, --quiet` | 安静模式，减少输出 |

## 配置

可通过环境变量调整默认行为：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `GUJI_OUTPUT_DIR` | 下载目录 | `./downloads` |
| `GUJI_CONCURRENT_DOWNLOADS` | 同时下载数量 | `4` |
| `GUJI_DEBUG` | 调试模式 | `false` |

也可以用配置文件：

```bash
bookget --config config.json download "URL"
```

## 许可证

MIT
