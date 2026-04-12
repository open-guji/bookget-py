# 项目总览

## 语言
- 始终使用中文进行交流和输出

## 用途
Bookget 是一个古籍数字资源下载与管理工具，支持从 50+ 个数字图书馆网站下载古籍的图片和文字资源。全异步架构，插件式适配器设计。

## 技术栈
- Python >= 3.10, 异步架构 (aiohttp + asyncio)
- 依赖: aiohttp, requests | 开发: pytest, ruff
- 入口: `python -m bookget` 或 `bookget` CLI

## 核心架构

```
bookget/
├── main.py                  # CLI 入口 (download/metadata/sites 三个命令)
├── config.py                # 配置管理 (DownloadConfig, StorageConfig)
├── exceptions.py            # 异常体系 (15+ 自定义异常)
├── core/
│   └── resource_manager.py  # 核心协调器，串联适配器→下载器→存储
├── models/
│   └── book.py              # 数据模型 (BookMetadata, Resource, DownloadTask)
├── adapters/                # 网站适配器 (14 个已实现)
│   ├── base.py              # BaseSiteAdapter 抽象基类
│   ├── registry.py          # 适配器自动发现与注册
│   ├── iiif/                # IIIF 站点: Harvard, NDL, Princeton, Stanford, Berkeley
│   └── other/               # 独立站点: NLC Guji, CText, Shidianguji, Hanchi, Wikisource, Archive.org, BnF, BL, BSB, 台湾NCL/NPM
├── downloaders/             # 下载器 (ImageDownloader, IIIFImageDownloader, TextDownloader)
├── storage/
│   └── file_storage.py      # 文件存储管理，目录结构规范
├── text_parsers/            # 文本解析器 (CText, Shidianguji, Wikisource)
│   └── base.py              # StructuredText 结构化文本模型
├── text_converters/         # Markdown / PlainText 转换器
└── scripts/
    └── siku_catalog_parser.py  # 四库全书目录解析辅助脚本
```

## 关键设计模式
- **适配器模式**: 每个网站一个适配器，继承 BaseSiteAdapter，通过 registry 自动发现
- **添加新站点**: 在 adapters/ 下新建文件，继承基类，实现 extract_book_id / get_metadata / get_image_list
- **结构化文本**: StructuredText 统一格式，包含 chapters → paragraphs 层级
- **断点续传**: .download_state.json 记录下载进度
- **配置来源**: 环境变量 (GUJI_*) > 配置文件 (JSON) > 默认值

## 实现状态
- 核心基础设施: 完成
- 14 个网站适配器: 完成
- 文字资源支持: 部分实现
- 预处理管道 / 50+ 站点扩展: 计划中

## 开发约定
- 测试: `pytest tests/`
- 代码检查: `ruff check bookget/`
