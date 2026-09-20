# 发布新版本

将 bookget 发布到 GitHub Release + PyPI。参数格式：`版本号`（如 `0.2.0`），不带 `v` 前缀。

## 发布步骤

### 1. 预检查

- 确认当前分支是 `main`，工作区干净（无未提交的改动）
- 确认 `pyproject.toml` 中的 `version` 字段已更新为目标版本
- 如果版本号未更新，先修改 `pyproject.toml` 并提交

### 2. 更新版本号

编辑 `pyproject.toml`：

```toml
version = "$ARGUMENTS"
```

如果有改动，提交：

```bash
git add pyproject.toml
git commit -m "release: v$ARGUMENTS"
```

### 3. 发 tag 前先空跑一次 workflow

tag 一旦推上去，PyPI 上传**不可撤销**（同版本号不能重传）。先手动触发一次
验证构建链路——`pypi` / `release` 两个 job 都有 `if: startsWith(github.ref,
'refs/tags/')` 守卫，手动触发只跑 `build`（三平台构建 + selftest 冒烟），
不发布任何东西：

在 https://github.com/open-guji/bookget-py/actions/workflows/release.yml
点 "Run workflow"（分支选 `main`），等三个平台全绿再进行下一步。

### 4. 打 tag 并推送

```bash
git tag v$ARGUMENTS
git push origin v$ARGUMENTS   # 只推 tag，不动分支
```

推送 tag 后，GitHub Actions 会自动：
1. 在 Windows、macOS、Linux 三个平台构建 `bookget-cli` 和 `bookget-ui`
2. 构建 sdist + wheel 并发布到 PyPI（Trusted Publisher OIDC）
3. 创建 GitHub Release，附带 6 个可执行文件

### 5. 验证

- GitHub Actions 构建页面：`https://github.com/open-guji/bookget-py/actions`
- Release 页面：`https://github.com/open-guji/bookget-py/releases/tag/v$ARGUMENTS`
- PyPI 页面：`https://pypi.org/project/bookget/$ARGUMENTS/`

## PyPI Trusted Publisher 配置

首次使用需在 PyPI 项目设置中配置 Trusted Publisher：

1. 前往 https://pypi.org/manage/project/bookget/settings/publishing/
2. 添加 GitHub publisher：
   - Owner: `open-guji`
   - Repository: `bookget-py`
   - Workflow: `release.yml`
   - Environment: （留空）

配置一次后，后续发布全自动，无需 API token。

## 注意事项

- 版本号遵循 semver（如 0.2.0、1.0.0）
- tag 必须以 `v` 开头（如 `v0.2.0`）才能触发 CI
- PyPI 发布与可执行文件构建并行进行，互不阻塞
- 如果 PyPI 上还没有 `bookget` 这个项目名，第一次需要手动发布以占位
