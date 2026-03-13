# 开发者指南

## 环境搭建

```bash
# 克隆仓库
git clone https://github.com/nichuanfang/bookget-py.git
cd bookget-py

# 安装开发依赖
pip install -e ".[dev,browser]"
playwright install chromium

# 代码检查
ruff check bookget/

# 运行测试
pytest tests/
```

## 项目结构

```
bookget/
├── main.py                  # CLI 入口，命令解析，交互模式
├── config.py                # 配置管理 (DownloadConfig, StorageConfig)
├── exceptions.py            # 异常体系 (15+ 自定义异常)
├── logger.py                # 日志配置
├── utils.py                 # 工具函数
├── core/
│   └── resource_manager.py  # 核心协调器，串联 适配器→下载器→存储
├── models/
│   ├── book.py              # BookMetadata, Resource, Creator
│   └── manifest.py          # DownloadManifest, ManifestNode (树形清单)
├── adapters/                # 网站适配器
│   ├── base.py              # BaseSiteAdapter 抽象基类
│   ├── registry.py          # 自动发现与注册
│   ├── iiif/                # IIIF 协议站点
│   │   ├── base_iiif.py     #   IIIF 基类 + GenericIIIFAdapter
│   │   ├── harvard.py
│   │   ├── ndl.py
│   │   ├── princeton.py
│   │   └── stanford.py      #   含 Berkeley 子类
│   └── other/               # 独立站点
│       ├── archive_org.py
│       ├── ctext.py
│       ├── european.py      #   BnF + BL + BSB
│       ├── hanchi.py
│       ├── nlc_guji.py
│       ├── shidianguji.py   #   使用 Playwright 浏览器自动化
│       ├── taiwan.py        #   NCL + NPM
│       └── wikisource.py
├── downloaders/             # 下载器
│   ├── base.py              #   ImageDownloader, TextDownloader
│   └── iiif.py              #   IIIFImageDownloader
├── storage/
│   └── file_storage.py      # 文件存储，目录结构管理
├── text_parsers/            # 网页→结构化文本
│   ├── base.py              #   StructuredText 数据模型
│   ├── ctext_parser.py
│   ├── hanchi_parser.py
│   ├── shidianguji_parser.py
│   └── wikisource_parser.py
├── text_converters/         # 结构化文本→输出格式
│   ├── markdown_converter.py
│   └── plaintext_converter.py
└── server/                  # Web UI 后端
    ├── app.py               #   aiohttp 应用工厂
    ├── routes.py            #   REST API 路由
    ├── tasks.py             #   异步任务管理
    ├── sse.py               #   Server-Sent Events
    └── static.py            #   静态文件服务
```

### 前端

```
ui/
├── app/                     # Web UI 应用 (React + Vite + TypeScript)
├── src/                     # npm 库源码
├── dist-app/                # 构建产物，嵌入到 bookget-ui 可执行文件
├── package.json
└── vite.config.ts
```

### 打包

```
packaging/
├── build.py                 # 构建脚本 (Windows + macOS)
├── cli.spec                 # PyInstaller CLI 配置
└── ui.spec                  # PyInstaller UI 配置 (含前端资源)
```

## 核心流程

```
用户输入 URL
    ↓
AdapterRegistry.get_for_url(url)  → 匹配适配器
    ↓
ResourceManager.discover()        → 调用适配器获取书籍结构
    ↓
ResourceManager.download_incremental()
    ├── adapter.get_image_list()  → 获取图片 URL 列表
    ├── adapter.get_structured_text()  → 获取文字内容
    ├── ImageDownloader.download() → 并行下载图片
    └── FileStorage.save()        → 保存到本地
```

## 添加新网站适配器

1. 在 `adapters/other/` 下创建新文件（IIIF 站点放 `adapters/iiif/`）

2. 继承 `BaseSiteAdapter`，实现必要方法：

```python
from bookget.adapters.base import BaseSiteAdapter
from bookget.adapters.registry import AdapterRegistry
from bookget.models.book import BookMetadata, Resource

@AdapterRegistry.register
class MyAdapter(BaseSiteAdapter):
    site_name = "我的站点"
    site_id = "my_site"
    base_urls = ["example.com"]

    # 能力声明
    supports_images = True
    supports_text = False

    def extract_book_id(self, url: str) -> str:
        """从 URL 提取书籍 ID"""
        ...

    async def get_metadata(self, book_id: str, *, index_id: str = "") -> BookMetadata:
        """获取书籍元数据"""
        ...

    async def get_image_list(self, book_id: str, *, index_id: str = "") -> list[Resource]:
        """获取图片资源列表"""
        ...
```

3. 在 `registry.py` 的 `_ADAPTER_MODULES` 列表中添加模块路径（PyInstaller 需要）

4. 在 `packaging/cli.spec` 和 `packaging/ui.spec` 的 `hiddenimports` 中添加模块

### 可选方法

| 方法 | 用途 |
|------|------|
| `get_structured_text()` | 获取结构化文字内容 |
| `get_text_content()` | 获取纯文本内容 |
| `get_iiif_manifest()` | 获取 IIIF Manifest |
| `get_pdf_url()` | 获取 PDF 下载链接 |
| `discover_structure()` | 自定义结构发现逻辑 |
| `download_node()` | 自定义节点下载逻辑 |

## 结构化文本

文本解析器将网页内容转为统一的 `StructuredText` 格式：

```
章节 (chapter)
  └── 段落 (paragraph)
        └── 文本内容
```

支持的 `content_type`：`single_chapter`、`book_with_chapters`、`catalog_entries`、`commentary`、`poetry_collection`

转换器将 `StructuredText` 输出为 Markdown 或纯文本。

## Server API

Web UI 后端提供以下 API：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sites` | GET | 列出支持的网站 |
| `/api/sites/check?url=` | GET | 检查 URL 是否支持 |
| `/api/discover` | POST | 发现书籍结构 |
| `/api/expand` | POST | 展开清单节点 |
| `/api/download` | POST | 开始下载任务 |
| `/api/download/{task_id}` | DELETE | 取消下载 |
| `/api/tasks` | GET | 列出所有任务 |
| `/api/tasks/{task_id}` | GET | 查询任务状态 |
| `/api/events` | GET | SSE 事件流 |

## 配置系统

优先级：环境变量 (`GUJI_*`) > 配置文件 (JSON) > 默认值

### DownloadConfig

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `concurrent_downloads` | 4 | 并行下载数 |
| `retry_attempts` | 3 | 重试次数 |
| `retry_delay` | 1.0 | 重试间隔（秒） |
| `timeout` | 30.0 | 请求超时（秒） |
| `request_delay` | 0.5 | 请求间隔（限流） |
| `min_image_size` | 1024 | 最小有效图片字节数 |

### StorageConfig

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `output_root` | `./downloads` | 输出根目录 |
| `cache_dir` | `./.cache` | 缓存目录 |
| `temp_dir` | `./.temp` | 临时目录 |

## 构建可执行文件

```bash
# 构建全部
python packaging/build.py

# 仅构建 CLI
python packaging/build.py cli

# 仅构建 UI（会先编译前端）
python packaging/build.py ui
```

产物输出到 `dist/` 目录。

### GitHub Actions 自动构建

推送 `v*` 标签自动触发 Windows + macOS 双平台构建，产物上传到 GitHub Releases：

```bash
git tag v0.1.0
git push --tags
```

## 发布到 PyPI

```bash
# 构建 sdist + wheel
python -m build

# 上传
python -m twine upload dist/*.tar.gz dist/*.whl
```
