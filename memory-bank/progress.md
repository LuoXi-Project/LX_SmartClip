# LX_SmartClip 开发进度记录

## 当前阶段
Phase 1 已完成，等待验证通过后进入 Phase 2。

---

## 已完成工作

### Phase 0：环境搭建与项目骨架（✅ 完成）

**完成时间：** 初始开发阶段

**完成内容：**
- 创建 Python 虚拟环境（venv，位于项目根目录 `venv/`）
- 创建 `backend/` 目录结构：`app/`、`app/api/`、`app/core/`、`app/db/`
- 初始化 `requirements.txt`，安装核心依赖：`fastapi`、`uvicorn[standard]`、`pydantic>=2.0`、`python-multipart`、`aiosqlite`
- 创建 `app/main.py`：注册 FastAPI 应用、CORS 中间件、lifespan 钩子、`GET /health` 接口

**验证结果：**
```
GET /health → {"status": "ok"}  ✅
```

---

### Phase 1：数据库基础层（✅ 完成）

**完成时间：** 2026-03-22

#### 1.1 SQLite 数据库初始化

**完成内容：**
- 创建 `app/db/database.py`：提供 `get_db_conn()` 异步连接函数（返回 aiosqlite.Connection，调用方负责关闭），以及 `get_db()` 异步生成器（用于依赖注入）
- 创建 `app/db/init_db.py`：定义建表 SQL（`videos`、`clips`、`config` 三张表），服务启动时通过 FastAPI lifespan 自动执行，使用 `CREATE TABLE IF NOT EXISTS` 保证幂等
- 数据库文件路径：`backend/data/smartclip.db`

**表结构说明：**
- `videos`：原视频记录，含 `id`、`name`、`file_path`、`duration`、`total_clips`、`split_mode`、`status`（pending/processing/done/error）、`upload_at`
- `clips`：片段记录，含 `id`、`video_id`、`clip_path`、`start_time`、`end_time`、`duration`、`asr_text`、`vlm_description`、`tags`
- `config`：全局配置表，含 `key`、`value`、`type`、`label`、`options`

**验证结果：**
```
Tables: ['clips', 'config', 'videos']  ✅
Config rows: 11  ✅
All Phase 1 checks PASSED  ✅
```

#### 1.2 全局配置表初始化

**完成内容：**
- `init_db.py` 中使用 `INSERT OR IGNORE` 写入 11 条默认配置（幂等，不覆盖已有值）
- 创建 `app/api/config.py`：实现 `GET /api/config`（返回全部配置）和 `PATCH /api/config`（先校验 key 存在再更新，不存在返回 404）
- 在 `main.py` 中注册 `config_router`，前缀为 `/api/config`

**默认配置项：**
| key | 默认值 | 类型 |
|-----|--------|------|
| split_mode | scene | select |
| fixed_duration | 10 | number |
| scene_threshold | 0.4 | number |
| vector_dimension | 1536 | number |
| top_k | 12 | number |
| vlm_provider | openai | select |
| vlm_base_url | https://api.openai.com/v1 | string |
| vlm_model | gpt-4o | string |
| vlm_api_key | （空） | string |
| tts_provider | edge-tts | select |
| asr_model | base | select |

**Bug 修复：** 原 `PATCH` 接口先执行 UPDATE 再判断 key 是否存在（UPDATE 不存在的 key 静默成功），修复为先查询 key 是否存在，不存在直接返回 404，再执行 UPDATE。

**验证结果：**
```
GET  /api/config        → 返回 11 个配置项 JSON  ✅
PATCH /api/config {key:top_k, value:20} → {key: top_k, value: 20}  ✅
PATCH 不存在的 key      → 404  ✅
```

---

## 下一步：Phase 2 — 视频上传与管理

等待用户确认 Phase 1 验证通过后执行。

**Phase 2 任务预览：**
- 创建 `storage/videos/` 上传目录
- 创建 `app/api/videos.py`：`POST /api/videos/upload`、`GET /api/videos`、`DELETE /api/videos/{id}`
- 写入 `videos` 表记录，返回视频 id

---

## 技术决策记录

### 1. 数据库路径策略
`DB_PATH` 使用 `__file__` 相对路径计算绝对路径（`init_db.py` 所在目录向上两级 + `data/smartclip.db`），保证无论从哪个工作目录启动都能找到正确位置。

### 2. 连接管理策略
提供两种连接方式：
- `get_db_conn()`：返回裸连接，适合简单路由（调用方 finally 关闭）
- `get_db()`：异步生成器，适合 FastAPI Depends 依赖注入（后续路由推荐使用）

### 3. PATCH 接口设计
先查询 key 存在性再更新，而非依赖 UPDATE 的影响行数，语义更清晰，错误提示更友好。

### 4. Windows 开发环境
- venv 位于 `f:\LuoXi-Project\LX_SmartClip\venv\`
- uvicorn 启动命令需要指定 `--host 127.0.0.1`
- PowerShell 中使用 `;` 分隔命令（不支持 `&&`）

