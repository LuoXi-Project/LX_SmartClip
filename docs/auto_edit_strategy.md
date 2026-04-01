# 智能剪辑（Auto Edit）实现逻辑与策略（`backend/app/api/auto_edit.py`）

本文档记录当前版本“智能剪辑/一键成片”的后端实现逻辑、策略假设与关键可调点，便于后续迭代与排障。

## 总览：两阶段架构

- **Phase 1：Plan 规划（LLM 生成结构化剪辑方案）**
  - 输入：用户提示词 + 已处理素材上下文（clip 列表、ASR 台词、VLM 画面描述等）
  - 输出：严格符合 schema 的 `Plan` JSON（候选 plans 列表）
  - 特点：只负责“怎么剪”的结构化描述，不直接渲染视频

- **Phase 2：Plan 落地（把 Plan 转成可导出的字幕/成片管线）**
  - 输入：前端选定的 `Plan`
  - 输出：成片文件（当前主要通过“字幕/导出”既有接口实现），并可选做 **BGM 混音后处理**
  - 特点：当前实现偏“最小可用”，对转场、keep_flags 等只做占位或忽略

## 关键数据结构（Plan Schema 的意图）

### `Plan`

- **`plan_id/title/summary`**：对外展示与索引。
- **`mode`**：`auto | voiceover | original`
  - 规划阶段可给建议；落地阶段用于选择导出路径。
- **`target_duration_sec / estimated_duration_sec`**：约束与展示。
- **`segments`**：真正的“剪辑规划结果”，按时间顺序拼接。
- **`bgm`（可选）**：是否启用背景音乐，以及选曲/音量/淡入淡出等参数。
- **`constraints/keep_flags`（可选）**：用于未来扩展；当前落地阶段多数不严格执行。

### `SegmentPlan`

每段包含“要用哪些素材片段 + 这段说什么/怎么配音 + 该段时间窗”：

- **`clip_group`**：候选素材集合（含 `video_id` 与权重）。
- **`selected_clip_ids`**：该段最终选中的 clip（规划阶段会给出多个备选，落地阶段当前只取第一个作为主片段）。
- **`start_time_sec/end_time_sec`**：段落时间窗（用于拼接与回退选段）。
- **`audio_mode`**：`original | tts | mute`
- **`subtitle`**：该段字幕策略与字幕文本（既可来源 ASR，也可由 LLM 重写/补写）。
- **`transition`**：占位（当前落地阶段不做真实转场渲染）。

## Phase 1：Plan 规划（LLM 生成）策略

对应接口：

- `POST /api/auto-edit/plan`
- `POST /api/auto-edit/plan/session` + `GET /api/auto-edit/plan/stream`（SSE 流式）

### 1) 上下文构建

后端从数据库读取 LLM 配置，并构建素材上下文：

- **LLM 配置**：通过 `LLMConfig.get_llm_params_with_defaults(...)` 获取（base_url / api_key / model / temperature / max_tokens 等）。
- **素材上下文**：通过 `app.api.copy_gen._build_video_context(db, video_ids)` 生成文本上下文（内含 clip_id、ASR、VLM 等摘要信息）。

### 2) Prompt 与 Schema 约束

`SYSTEM_PROMPT` 的核心约束是：

- **clip_id 必须原样拷贝**：模型只能使用上下文里出现过的 `[clip_id=XXXXX]`，禁止凭空创造新 ID。
- **只输出 JSON**：顶层结构必须是 `{"plans":[Plan,...]}`，不得夹带解释。
- **时间单位统一秒（float）**：并要求 segments 尽量“首尾相接”、整体时长接近目标时长。

用户消息 `_build_user_message(context, req)` 会把以下“生成要求”明确写入：

- 模式（`mode`）
- 目标时长（可选）
- 候选方案数量（`num_plans`）
- 是否允许跨视频重排（`allow_cross_video`）
- 字幕/转场/BGM 策略（`subtitle_policy/transition_policy/bgm_policy`）
- 以及“可用素材简要信息”（context）

此外还会拼接 `SCHEMA_HINT`，把 JSON 结构的样例/字段约束再写一遍，用于降低结构跑偏概率。

### 3) 输出清洗与强校验（防“带 Markdown / 伪 JSON”）

LLM 返回后会做三层防护：

1. `_extract_json_array(raw)`：
   - 移除 `<think>...</think>` 等思维链包裹
   - 若包含 ``` 代码块，优先取代码块内容
   - 兜底截取第一个 `{` 到最后一个 `}` 的范围
2. `json.loads(cleaned)`：直接解析
3. 若解析失败，尝试 `json_repair.repair_json` 修复后再解析（作为兜底）

最终再通过 Pydantic：

- `AutoEditPlanResponse(**data)` 强校验 Plan 结构；失败则返回 502（“Plan 结构不符合预期”）。

### 4) 流式（SSE）规划会话策略

- `create_auto_edit_plan_session` 生成 `session_id`，把请求体暂存于内存字典 `_PLAN_STREAM_SESSIONS`，并记录创建时间。
- `stream_auto_edit_plan` 拉取并消费该 session（**一次性**），按阶段发 SSE：
  - `init`（读取模型配置）
  - `context`（构建素材上下文）
  - `llm`（生成候选方案）
  - `done`（完成）
  - 最终 `result` 事件携带完整 `plan_res.model_dump()`
- 有过期清理 `_cleanup_expired_plan_sessions()`（默认 10 分钟）。

## Phase 2：Plan 落地成片策略

对应接口：

- `POST /api/auto-edit/realize`

### 1) clip_id 预检：把“LLM 幻觉”转成“可容错的现实”

落地阶段首先收集 Plan 中所有可能用到的 clip_id：

- `_collect_plan_clip_ids(plan)`：遍历每段的 `selected_clip_ids` 与 `clip_group[*].clip_id` 去重汇总。

随后在 `clips` 表中查询这些 ID 是否存在：

- **有效 clip_id**：进入 `valid_clip_ids` 集合，并记录 `clip_id -> video_id` 映射。
- **无效 clip_id**：形成 `invalid_clip_ids` 列表。

如果最终无法转换出任何有效片段，会返回 400，并把 `invalid_clip_ids` 一并返回给前端，便于诊断。

### 2) 构建回退候选池（用于“段落选段自动兜底”）

为了在 `selected_clip_ids` 不可用时仍能导出，系统会建立候选池：

- 优先使用各段 `clip_group[*].video_id` 里出现的视频
- 其次使用已命中 `valid_clip_ids` 对应的视频

并从数据库把这些视频的所有 clip（`id, video_id, start_time, end_time, duration`）读出，形成：

- `candidates`：全量候选 `ClipCandidate` 列表
- `candidates_by_video`：按 `video_id` 分组

### 3) Plan → `SubtitleSegmentInput` 的转换规则（当前“最小版”）

核心函数：`_segments_from_plan(...)`

对每个 `SegmentPlan`：

- **主片段选择顺序**
  1. `selected_clip_ids` 中第一个且在 `valid_clip_ids` 内的 clip
  2. 否则回退 `clip_group` 中第一个有效 clip
  3. 再否则调用 `_pick_fallback_clip(...)`，按时间窗从候选池选“最接近”的 clip：
     - 评分优先最大化 overlap（与段落时间窗交集）
     - overlap 相同则选择中心点距离更近的
- **音频策略**
  - 若 `audio_mode == "tts"` 且有字幕文本，则直接调用 `app.api.tts.synthesize` 生成语音文件，填到 `SubtitleSegmentInput.tts_filename`
  - 否则走原声/静音逻辑由下游管线处理（当前主要依赖既有 `subtitle`/`export_original` 接口）
- **字幕文本**
  - `copy_text` 取 `seg.subtitle.text`（为空则置空字符串）

最终生成 `SubtitleSegmentInput` 列表 `seg_inputs`，作为后续字幕与导出接口的统一输入。

### 4) 导出路径选择（voiceover vs original）

`realize_auto_edit_plan` 的导出分两条主路径：

- **`plan.mode in ("auto", "voiceover")`**：统一走“配音/字幕管线”
  - 若 `include_subtitle=True`：
    - `generate_srt(segments, use_tts_timing=True)`：优先以 TTS 时长生成时间轴
    - `burn_subtitle(...)`：渲染字幕并导出成片
  - 若 `include_subtitle=False`：
    - 走 `export_original(..., include_subtitle=False, normalize_audio=True)` 输出不带字幕的视频

- **`plan.mode == "original"`**：走原声导出
  - `export_original(..., include_subtitle=req.include_subtitle, normalize_audio=True)`

注意：当前注释与实现存在一个“现实差异点”：

- 注释写“original 模式按段落平均切字幕”，但实际仍依赖 `SubtitleSegmentInput` + `export_original` 的既有行为；若需要“平均切分/重新分配字幕”，需要在 `export_original` 或本模块补充显式策略。

### 5) BGM 后处理（可选启用）

虽然 `realize` 的 docstring 写“忽略 BGM”，但当前代码已经实现了一个 **后处理混音**：

- `_apply_bgm_postprocess_if_needed(plan, filename, url)`：
  - 若 `plan.bgm.enabled` 为真，则尝试解析/选择 BGM 音频并对成片做混音，失败则回退原成片。

#### 5.1 BGM 路径解析优先级

`_resolve_bgm_path(track_id)` 的候选顺序：

1. `track_id` 是绝对路径：直接尝试
2. 相对 `backend` 根目录拼接
3. 约定目录：`backend/storage/bgm`

#### 5.2 自动选曲策略（最小可用）

`_choose_auto_bgm_track(plan)`：

- 优先从 `storage/bgm/bgm_manifest.json` 读元数据（`_choose_bgm_from_manifest`）：
  - 通过 `Plan` 的标题/摘要/字幕文本抽取关键词
  - 先判定目标情绪（happy/calm/epic/sad/tech），再对 manifest 里 track 做打分：
    - mood 字段强匹配加分
    - title/tags 命中情绪关键词加分
    - 文本 token 命中 title/tags 宽松加分
    - bpm 接近 preferred_bpm 加分（按情绪给粗略目标 bpm）
- 若无 manifest 或无法命中，则扫描 `storage/bgm` 下音频文件名做 token 打分；若都不命中则回退第一个文件。

#### 5.3 混音实现（FFmpeg）

`_mix_bgm_for_video(...)`：

- 用 `ffprobe` 探测成片时长
- 对 BGM 做：
  - `volume`（dB）
  - `afade` 淡入/淡出（淡出起点按“视频总时长 - fade_out”计算）
  - 可选 `aloop` + `atrim` 以 loop 到视频长度
- 最终 `amix` 与原声混合，输出到 `backend/storage/burned_videos/*_bgm_XXXXXX.mp4`

## 当前版本的“策略边界”（重要）

- **转场**：`Plan.transition` 仅占位，落地阶段不做真实渲染。
- **keep_flags / prev_plan**：规划请求里虽有字段，但当前实现只做“全量新方案”，落地阶段也基本忽略。
- **多 clip 拼接**：`SegmentPlan.selected_clip_ids` 虽允许多个，但落地阶段目前只取“第一个有效 clip”作为主片段；其余 ID 仅作为 `clip_ids` 传给下游，是否参与拼接取决于下游实现。
- **严格时长控制**：规划阶段要求“segments 首尾相接、接近目标时长”，但落地阶段仍以既有字幕/导出管线为准；若要保证“严格时长=target_duration_sec”，需引入显式裁切/拼接与时间轴对齐。

## 可调参数与建议默认值（当前实现位置）

- **LLM 参数**：`LLMConfig.get_llm_params_with_defaults(...)`
  - `default_temperature=0.7`
  - `default_max_tokens=20480`
- **SSE 会话过期**：`_PLAN_STREAM_EXPIRE_SEC = 10 * 60`
- **BGM 默认值**（`BGMPlan`）：
  - `volume_db=-12.0`, `fade_in_sec=0.8`, `fade_out_sec=1.0`, `loop=True`
- **字幕样式**：落地时固定 `SubtitleStyle()`（后续可前端透传参数）

## 关键函数/接口索引（便于代码跳转）

- 规划：
  - `generate_auto_edit_plan`：一次性返回 plans
  - `create_auto_edit_plan_session` / `stream_auto_edit_plan`：SSE 流式生成
  - `_call_llm_for_plans`：LLM 调用 + JSON 清洗 + Pydantic 校验
- 落地：
  - `realize_auto_edit_plan`：Plan → 成片
  - `_segments_from_plan`：Plan segment → `SubtitleSegmentInput`（主策略点）
  - `_pick_fallback_clip`：无效 clip 的时间窗兜底选段
- BGM：
  - `_apply_bgm_postprocess_if_needed`：后处理混音入口
  - `_choose_auto_bgm_track` / `_choose_bgm_from_manifest`：自动选曲
  - `_mix_bgm_for_video`：FFmpeg 混音实现

