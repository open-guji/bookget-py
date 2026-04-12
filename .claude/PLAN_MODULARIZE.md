# bookget 模块化重构计划

## Context

bookget-py 目前只能作为 Python 模块 / CLI 使用，guji-platform（VS Code 扩展）通过 PythonBridge spawn 进程调用它。下载管理的 React UI 组件（ManifestTree、进度条等）耦合在 guji-platform 内部。

**目标**：将 bookget 打造为一个通用的古籍下载工具，支持三种使用方式：
1. VS Code 扩展标签页（现有，改为引用独立组件库）
2. 独立 Web 应用（`bookget serve` 启动 server + 浏览器 UI）
3. 两个独立 exe（`bookget-cli` 交互式命令行，`bookget-ui` 内置 Web 服务）

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  使用方式 (Shells)                                       │
│  ┌───────────┐  ┌────────────┐  ┌────────┐ ┌─────────┐ │
│  │ VS Code   │  │ Standalone │  │bookget │ │bookget │ │
│  │ Extension │  │ Web App    │  │-cli.exe│ │-ui.exe │ │
│  └─────┬─────┘  └──────┬─────┘  └────────┘ └────┬────┘ │
│        │               │                         │      │
├────────┼───────────────┼─────────────────────────┼──────┤
│        │    ┌──────────┴─────────────────────────┴──┐   │
│        │    │  bookget-ui (npm 组件库)               │   │
│        │    │  React 组件 + TransportAdapter 抽象    │   │
│        │    └──────────┬────────────────────────────┘   │
│        │               │                                │
│  VscodeTransport   HttpTransport                        │
│  (postMessage)     (REST + SSE)                         │
│        │               │                                │
├────────┼───────────────┼────────────────────────────────┤
│  guji-platform     bookget.server                       │
│  (PythonBridge     (aiohttp HTTP API)                   │
│   → CLI 调用)          │                                │
│        │               │                                │
│        └───────┬───────┘                                │
│          bookget 核心                                    │
│          (ResourceManager, Adapters, Models)             │
└─────────────────────────────────────────────────────────┘
```

---

## A. bookget-py: 新增 server 模块

### 目录结构

```
bookget/
├── server/                 # 新增
│   ├── __init__.py
│   ├── app.py              # aiohttp Application 工厂
│   ├── routes.py           # REST API 路由
│   ├── sse.py              # SSE 事件流管理
│   ├── tasks.py            # TaskManager（管理活跃下载任务）
│   └── static.py           # 静态文件服务（serve 前端 dist）
├── main.py                 # 新增 `serve` 子命令
└── ...（现有不变）
```

### HTTP API

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/sites` | 列出支持的站点 |
| `GET` | `/api/sites/check?url=...` | 检查 URL 是否支持 |
| `POST` | `/api/discover` | 发现结构 `{url, outputDir?, depth?}` → ManifestData |
| `POST` | `/api/expand` | 展开节点 `{url, outputDir, nodeId}` → ManifestData |
| `POST` | `/api/download` | 启动下载 `{url, outputDir, nodeIds?, concurrency?}` → taskId |
| `DELETE` | `/api/download/{taskId}` | 取消下载 |
| `GET` | `/api/tasks` | 列出活跃任务 |
| `GET` | `/api/tasks/{taskId}` | 任务详情（含 manifest） |
| `DELETE` | `/api/nodes` | 删除已下载节点 `{taskId, nodeIds}` |
| `GET` | `/api/events` | **SSE** 全局事件流 |

### SSE 事件类型

```
event: progress         data: {taskId, completed, total, percent, nodeId, title}
event: manifest_updated data: {taskId, manifest: ManifestData}
event: task_completed   data: {taskId}
event: task_error       data: {taskId, message}
event: log              data: {taskId, text}
```

### TaskManager（新增薄封装）

```python
# bookget/server/tasks.py
class TaskManager:
    def __init__(self, config: Config):
        self.manager = ResourceManager(config)
        self.tasks: dict[str, TaskInfo] = {}
        self._subscribers: list[asyncio.Queue] = []

    async def start_discover(self, url, output_dir, depth) -> ManifestData
    async def start_download(self, url, output_dir, node_ids, concurrency) -> str  # → taskId
    async def cancel(self, task_id) -> bool
    async def expand_node(self, url, output_dir, node_id) -> ManifestData
    def subscribe(self) -> asyncio.Queue    # SSE 订阅
    def unsubscribe(self, queue)            # SSE 取消订阅
```

### CLI 新增

```bash
bookget serve [--port 8765] [--host 127.0.0.1] [--no-open] [--output-dir ./downloads]
```

---

## B. bookget-ui: npm React 组件库

### 目录结构（在 bookget-py 项目下）

```
bookget-py/
├── ui/                              # 新增
│   ├── package.json                 # name: "bookget-ui"
│   ├── tsconfig.json
│   ├── vite.config.ts               # 库模式 + 应用模式
│   ├── src/
│   │   ├── index.ts                 # 公共导出入口
│   │   ├── types.ts                 # ManifestNode, ManifestData 等共享类型
│   │   ├── transport/
│   │   │   ├── types.ts             # TransportAdapter 接口定义
│   │   │   ├── http-transport.ts    # REST + SSE（独立 Web 用）
│   │   │   └── vscode-transport.ts  # postMessage（VS Code 用）
│   │   ├── hooks/
│   │   │   ├── useDownloadManager.ts   # 核心状态管理
│   │   │   └── useManifestTree.ts      # 树操作（选中、折叠、展开）
│   │   ├── components/
│   │   │   ├── DownloadDashboard.tsx # 顶层仪表盘
│   │   │   ├── ManifestTree.tsx     # 清单树
│   │   │   ├── ManifestToolbar.tsx  # 工具栏
│   │   │   ├── TaskList.tsx         # 活跃下载列表
│   │   │   ├── TaskCard.tsx         # 单个下载卡片
│   │   │   └── ProgressBar.tsx      # 通用进度条
│   │   ├── utils/
│   │   │   ├── tree-helpers.ts      # collectDownloadableLeaves 等
│   │   │   └── format.ts           # formatSize, getFileIcon
│   │   └── styles/
│   │       ├── variables.css        # --bdm-* CSS 变量
│   │       └── components.css
│   └── app/                         # 独立 Web 应用入口
│       ├── index.html
│       ├── main.tsx
│       └── App.tsx
```

### 核心接口: TransportAdapter

```typescript
interface TransportAdapter {
  discover(req: {url, outputDir?, depth?}): Promise<ManifestData>;
  startDownload(req: {taskId, url, outputDir, nodeIds?, concurrency?}): Promise<void>;
  cancelDownload(taskId: string): Promise<void>;
  expandNode(req: {taskId, url, outputDir, nodeId}): Promise<ManifestData>;
  deleteNodes(req: {taskId, nodeIds}): Promise<void>;
  getSupportedSites(): Promise<SiteInfo[]>;
  checkUrl(url: string): Promise<{supported: boolean, site?: SiteInfo}>;
  subscribe(listener: (event: DownloadEvent) => void): () => void;
  dispose(): void;
}
```

### 组件提取对应关系

| guji-platform 源 | bookget-ui 目标 |
|---|---|
| `init/web/App.tsx` ManifestSection (L425-545) | ManifestTree + ManifestToolbar |
| `init/web/App.tsx` ManifestNodeView (L549-648) | ManifestTree 内部 |
| `init/web/App.tsx` 辅助函数 (L652-726) | utils/tree-helpers.ts |
| `downloads/web/App.tsx` (L1-107) | TaskList + TaskCard |
| formatSize, getFileIcon | utils/format.ts |

**不提取**（留在 guji-platform）：ResourceCard, ResourceDetail, KnownResourceCard, StepLayout, useStepMessages

### CSS: 使用 `--bdm-*` 变量命名空间，VS Code 中映射到 `--vscode-*`

---

## C. guji-platform 改造（最小化）

1. package.json 添加 `"bookget-ui"` 依赖
2. init/web/App.tsx: ManifestSection → 导入 bookget-ui 组件
3. downloads/web/App.tsx: 替换为 bookget-ui 的 TaskList
4. Extension host 侧逻辑不变

---

## D. 两个 exe

- **bookget-cli.exe**: 核心 + 交互式 CLI（无参数时引导输入 URL）
- **bookget-ui.exe**: 核心 + server + 前端静态文件（双击自动打开浏览器）

---

## 实施步骤

### Phase 1: bookget-ui npm 组件库
1. `bookget-py/ui/` 初始化 npm + Vite + React
2. 定义 TransportAdapter 接口和共享类型
3. 提取工具函数
4. 提取 ManifestTree, ManifestToolbar 组件
5. 提取 TaskList, TaskCard 组件
6. 实现 useDownloadManager hook
7. 创建 DownloadDashboard
8. 实现 VscodeTransport
9. CSS 主题
10. 验证 build:lib

### Phase 2: guji-platform 集成
11. 添加 bookget-ui 依赖
12. 替换 init/web/App.tsx 中的组件
13. 替换 downloads/web/App.tsx
14. CSS 变量映射
15. 全面测试

### Phase 3: bookget server
16. 创建 server/ 目录
17. 实现 TaskManager
18. 实现 REST + SSE
19. 添加 serve 子命令
20. 实现 HttpTransport

### Phase 4: 独立 Web 应用
21. 创建 ui/app/ 入口
22. Vite dev proxy
23. build:app
24. 端到端测试

### Phase 5: exe 打包
25. 交互式 CLI 模式
26. PyInstaller spec
27. 构建和测试两个 exe

### Phase 6: 发布
28. npm publish + pip publish + GitHub Release

---

## 关键决策记录

- **Server 框架**: aiohttp（已有依赖，零新增）
- **npm 包名**: bookget-ui（无 scope）
- **exe**: 两个独立 exe（bookget-cli + bookget-ui）
- **实时通信**: SSE（单向推送，浏览器原生支持）
- **CSS**: --bdm-* 命名空间 + VS Code 映射
