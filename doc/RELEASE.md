# 发布流程

## 发布新版本

### 1. 更新版本号

编辑 `pyproject.toml` 中的 `version` 字段：

```toml
version = "0.2.0"
```

### 2. 提交并打 tag

```bash
git add -A
git commit -m "release: v0.2.0"
git tag v0.2.0
git push origin master --tags
```

### 3. 自动构建与发布

推送 tag 后，GitHub Actions 自动完成：

| 步骤 | 说明 |
|------|------|
| **build** | 在 Windows / macOS / Linux 构建 `bookget-cli` 和 `bookget-ui` |
| **pypi** | 构建 sdist + wheel，通过 Trusted Publisher (OIDC) 发布到 PyPI |
| **release** | 创建 GitHub Release，附带 6 个可执行文件 |

产物命名：
- `bookget-cli-windows.exe` / `bookget-cli-macos` / `bookget-cli-linux`
- `bookget-ui-windows.exe` / `bookget-ui-macos` / `bookget-ui-linux`

---

## PyPI Trusted Publisher 配置（首次）

GitHub Actions 使用 OIDC 令牌直接发布到 PyPI，无需 API token。首次需在 PyPI 配置：

1. 前往 https://pypi.org/manage/project/bookget/settings/publishing/
2. 添加 GitHub publisher：
   - **Owner**: `open-guji`
   - **Repository**: `bookget-py`
   - **Workflow**: `release.yml`
   - **Environment**: （留空）

> 如果 PyPI 上还没有 `bookget` 项目，第一次需要手动 `twine upload` 占位后再配置 Trusted Publisher。

---

## 用户使用方式

### 方式 A：下载 Release（最简单）

1. 前往 [Releases](https://github.com/open-guji/bookget-py/releases) 页面
2. 下载对应平台的文件
3. 双击运行（macOS/Linux 先 `chmod +x`）

### 方式 B：pip install

```bash
pip install bookget
bookget              # 交互模式
bookget download URL # 命令行模式
bookget serve        # 启动 Web 界面
```

---

## 本地构建测试

```bash
# 安装构建依赖
pip install -e ".[dev]"
pip install pyinstaller

# 构建前端
cd ui && npm install && npm run build:app && cd ..

# 构建可执行文件
python packaging/build.py       # 构建 cli + ui
python packaging/build.py cli   # 只构建 cli
python packaging/build.py ui    # 只构建 ui

# 产物在 dist/ 目录下
ls dist/
```

## 手动触发构建

在 GitHub Actions 页面手动触发 `Build & Release` workflow（workflow_dispatch），用于测试构建流程。手动触发只上传 artifacts，不会创建 Release 或发布 PyPI。
