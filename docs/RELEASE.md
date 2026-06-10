# 发版与升级指南

洛曦智剪采用 **私密源码仓 + 公开发版仓** 双仓库模式：

| 仓库 | 用途 |
|------|------|
| 私密仓（本仓库） | 源码、开发、本地打包 |
| 公开发版仓 `release.config.json → release_repo` | 仅 GitHub Releases，托管 zip 安装包 |

用户端通过公开发版仓的 GitHub Releases API 检查更新，**不需要自建服务器**。

---

## 一次性准备

### 1. 创建公开发版仓库

在 GitHub 新建 **公开** 仓库，例如：

`https://github.com/LuoXi-Project/LX_SmartClip-Releases`

仓库可以是空的，无需源码，只用来发 Release。

### 2. 配置 `release.config.json`

编辑仓库根目录 `release.config.json`：

```json
{
  "release_repo": "LuoXi-Project/LX_SmartClip-Releases",
  "asset_name_template": "LX_SmartClip-{version}-win64.zip"
}
```

### 3. （推荐）安装 GitHub CLI

```powershell
winget install GitHub.cli
gh auth login
```

---

## 每次发版流程

### 第一步：改版本号

编辑根目录 `VERSION`：

```
1.0.1
```

### 第二步：本地打包

**PyArmor 7 发版**（默认）需 **Python 3.10**（PyArmor 7 不支持 3.11+）。首次请先：

```bat
scripts\setup_release_py310.bat
```

然后：

```bat
scripts\prepare_release.bat
```

若改用 Nuitka（无需 PyArmor / 可用 Python 3.12），在 `release.config.json` 设 `"backend_builder": "nuitka"`。

```bat
scripts\prepare_release.bat
```

脚本会：

1. 同步版本到 `backend/app/version.json`、前端 `package.json`
2. 运行 `build_release.bat` 完整构建
3. 生成 `dist/release/LX_SmartClip-{version}-win64.zip`
4. 生成同名 `.sha256` 校验文件
5. 生成 `RELEASE_NOTES.md` 模板（含升级元数据 JSON）

### 第三步：编辑 Release 说明

打开 `dist/release/RELEASE_NOTES.md`，填写变更内容。

**普通升级**（只加列/加表，自动兼容）保持 JSON 为：

```json
{
  "schema_version": 1,
  "min_schema_version": 1,
  "breaking": false,
  "requires_backup": false
}
```

**破坏性数据库升级** 改为：

```json
{
  "schema_version": 2,
  "min_schema_version": 1,
  "breaking": true,
  "requires_backup": true
}
```

用户升级前会在设置页看到备份提示。

### 第四步：发布

**方式 A — 脚本自动发布（推荐）**

```bat
scripts\publish_release.bat
```

使用 `gh release create` 上传到 **公开发版仓**（不是私密源码仓）。

**方式 B — 手动发布**

1. 打开 `https://github.com/{release_repo}/releases/new`
2. Tag：`v1.0.1`（与 VERSION 一致）
3. 上传 `dist/release/LX_SmartClip-1.0.1-win64.zip`
4. 上传 `dist/release/LX_SmartClip-1.0.1-win64.zip.sha256`
5. 正文粘贴 `RELEASE_NOTES.md` 内容

---

## 用户端升级

设置 → **软件更新**：

- **检查更新**：对比 GitHub 最新 Release
- **备份数据**：复制 `smartclip.db` + `config.json` 到 `data/backups/`
- **立即升级**：下载 zip → 替换 exe/`_internal` → 自动重启（保留 `data/`、`storage/`、`config.json`）

---

## 私密仓 + GitHub Actions（可选）

私密仓库 **可以** 使用 GitHub Actions，但 Windows 打包耗时长、需 FFmpeg/Node/Python 环境。

更实用的做法：

- **本地 `prepare_release.bat` 打包**（当前方案）
- Action 只负责 **把已构建的 zip 推到公开发版仓**（需 PAT）

见 `.github/workflows/upload-release.yml`：手动触发，上传 `dist/release` 产物。

在私密仓 Settings → Secrets 添加：

| Secret | 说明 |
|--------|------|
| `RELEASE_REPO` | 例：`LuoXi-Project/LX_SmartClip-Releases` |
| `RELEASE_REPO_TOKEN` | PAT，对公开发版仓有 `contents: write` |

本地打包后 push tag，或手动 workflow_dispatch 上传 artifact。

---

## 数据库迁移开发约定

1. 在 `backend/app/db/schema.py` 递增 `CURRENT_SCHEMA_VERSION`
2. 在 `backend/app/db/migrations/__init__.py` 注册新迁移函数
3. 发版时在 `RELEASE_NOTES.md` JSON 中更新 `schema_version` / `min_schema_version`
4. 破坏性变更务必 `requires_backup: true`

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `VERSION` | 单一版本源 |
| `release.config.json` | 公开发版仓地址 |
| `scripts/prepare_release.bat` | 构建 + 打 zip |
| `scripts/publish_release.bat` | 发布到 GitHub |
| `scripts/tools/apply_update.template` | Windows 升级脚本模板（打包时写入 dist/tools/apply_update.ps1） |
| `backend/app/api/system.py` | 检查更新 / 备份 / 触发升级 API |
