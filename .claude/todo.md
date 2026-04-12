# 当前优先任务：识典古籍搜索功能

## 目标
为 `ShidianGujiAdapter` 添加 `search()` 和 `match_book()` 方法，使其支持书名搜索和精确匹配，用于批量搜索文字资源链接。

## 开发步骤

### 1. 浏览器复用机制
- 在 `ShidianGujiAdapter` 中添加 `_ensure_browser()` 和 `_close_browser()` 方法
- 修改 `close()` 方法以关闭持久化的浏览器实例
- 使浏览器实例可在多次 search/match 调用间复用

### 2. search() 方法
- 设置 `supports_search = True`
- 通过 Playwright 导航到搜索页面 `https://www.shidianguji.com/search?q={query}`
- 拦截 `POST /api/ancientlib/read/search/book/v1` 响应
- 解析返回的 bookList，提取 bookId、bookName、authors、dynastyCategoryName
- 返回 `SearchResponse` 对象

### 3. match_book() 方法
- 生成标题变体（繁简转换）
- 调用 search() 搜索各变体
- 标题精确匹配筛选（含异体字归一化）
- 作者三级匹配（全名 → 姓氏 → 回退接受）
- 返回 `list[MatchedResource]`

### 4. 繁简转换共享
- 考虑将 CText 中的 OpenCC + 异体字归一化逻辑抽取为共享模块
- 或直接在 shidianguji.py 中复用/导入

## 参考
- CText 适配器: `bookget/adapters/other/ctext.py` — search/match 实现模板
- 搜索模型: `bookget/models/search.py` — SearchResponse, MatchedResource
- 设计文档: `overview/古籍索引网站/文字资源搜索.md` 阶段三

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