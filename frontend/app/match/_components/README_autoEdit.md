# 自动成片（AutoEdit）前端结构说明

这个目录里，自动成片相关的代码已经按“容器层 + 视图层 + Hook/类型”的方式拆分，方便在大项目场景下演进和维护。

## 一、职责分层总览

- **容器组件**
  - `AutoEditPanel.tsx`
    - 作为“自动成片”在页面中的入口，仅负责：
      - 接收上层传入的 props（模式、BGM 配置、生成触发、一键成片回调等）
      - 维护跨区域业务状态：
        - `detailPlan / detailDraft / detailEditMode / customPlanById`
        - `selectedPreview`（当前预览的片段）
      - 调用 Hook 拉取依赖数据：`useAutoEditBgmTracks()`、`useAutoEditClipMetaByPlans()`
      - 将状态和回调下发给三个区域组件：
        - `AutoEditPlannerSection`：顶部配置 & 生成区域
        - `AutoEditCandidatesSection`：候选方案列表 + 预览
        - `AutoEditDetailModal`：方案详情弹窗（可编辑）

- **区域视图组件**
  - `AutoEditPlannerSection.tsx`
    - 顶部“自动一键成片 / 口播快剪 · 成片导出”区域：
      - 目标时长、方案个数、成片模式
      - BGM 混音策略（复用 `AutoEditBgmMixPanel`）
      - Timeline Engine / Explain 开关
      - 生成按钮 + 当前阶段进度条 + 文本日志
    - 该组件不持久化业务状态，只消费/触发由容器传入的回调。
  - `AutoEditCandidatesSection.tsx`
    - 中部“候选方案 · N 个”区域：
      - 内部维护局部 UI 状态：`expandedPreviewPlanIds`（每个方案卡片内片段列表的展开/收起）
      - 组合：
        - `AutoEditPreviewPanel`：顶部预览播放器
        - 多个 `AutoEditPlanCard`：每张方案卡片
      - 与容器交互：
        - 从 `AutoEditPanel` 接受 `selectedPreview` 和 `setSelectedPreview`
        - 通过 `onOpenDetailPlan`、`onRealizePlan` 通知容器。
  - `AutoEditDetailModal.tsx`
    - 方案详情弹窗，展示并允许编辑：
      - 方案摘要
      - 各段字幕文本、音频模式、clip 选择、时间轴、可控时长等
    - 内部使用大量 `setDetailDraft(prev => ...)` 方式更新 JSON，保证编辑逻辑集中在一个地方。

- **更细粒度视图 & 复用块**
  - `AutoEditPreviewPanel.tsx`
    - 负责片段预览播放器：
      - 从 `SelectedPreviewState` & `ClipMetaByClip` 计算：
        - `resolvedVideoId`（clip 映射到 video）
        - `previewTimeline`（plan 时间窗 vs. 库内绝对时间）
      - 管理 `video` 标签的 seek / play 行为以及 `previewVideoErr`。
  - `AutoEditPlanCard.tsx`
    - 单个候选方案卡片：
      - 标题、模式、BGM 概要
      - 含字幕标记
      - 段落统计、片段预览按钮（调用 `onSelectPreview`）
      - 一键成片按钮 + 生成中状态 + 下载链接
  - `AutoEditBgmMixPanel.tsx`
    - BGM 策略 + 成片 BGM 选择复用组件：
      - 支持定制：
        - 外层 `wrapperClassName`
        - 提示文案 `helperText`
        - 策略标签文案 `strategyLabel`
        - 空曲库提示前缀 `emptyBgmHintPrefix`
        - 规划阶段下拉禁用控制 `policySelectDisabled`
      - 被 `AutoEditPlannerSection` 在“隐藏模式”和“完整规划模式”两处复用。

- **Hook & 类型**
  - `autoEditPanelHooks.ts`
    - `useAutoEditBgmTracks()`
      - 拉取 BGM 列表，提供 `bgmTracks` / `bgmListError`
    - `useAutoEditClipMetaByPlans(autoPlans)`
      - 扫描所有方案中的 clip_id，批量请求 `/api/videos/clips/:id`，构建 `ClipMetaByClip` 映射。
  - `autoEditTypes.ts`
    - `AutoPlanStage`：方案生成阶段枚举
    - `ClipMeta` / `ClipMetaByClip`
    - `SelectedPreviewState`：预览选中信息（plan/segment/clip/time 等）
    - `PreviewTimeline`：预览时间轴结构（planStart/absStart/clipLocalEnd 等）

## 二、典型数据流（从生成到预览到成片）

1. **配置 & 生成**
   - 用户在 `AutoEditPlannerSection` 中调整：
     - `autoTargetDuration / autoNumPlans / autoMode`
     - BGM 策略 & 成片 BGM
     - 是否启用 Timeline Engine / Explain
   - 点击“生成自动成片方案”按钮：
     - 触发 `onGeneratePlans`（由上层页面实现，通常发请求、更新 `autoPlans` & 日志）
   - 生成过程中的阶段 & 文本日志：
     - 上层更新 `autoPlanStage` / `autoPlanStagePercent` / `autoPlanLogs` / `autoPlanElapsedSec`
     - `AutoEditPlannerSection` 负责展示进度条 + 分步标签 + 文案。

2. **候选方案列表 & 预览**
   - `AutoEditPanel` 接收到新的 `autoPlans` 后：
     - `useAutoEditClipMetaByPlans` 会根据所有方案里的 clip_id 预拉取 `ClipMetaByClip`
   - `AutoEditCandidatesSection`：
     - 对每个方案渲染一张 `AutoEditPlanCard`
     - 每个卡片里的“片段预览”按钮，会调用 `onSelectPreview`（实质上是 `setSelectedPreview`）
   - `AutoEditPreviewPanel` 监听 `selectedPreview` & `clipMetaByClip`：
     - 计算可用于对齐的时间轴 `PreviewTimeline`
     - 控制 `<video>` 的起点/终点跳转以及原视频/片段视角切换。

3. **方案详情编辑 & 一键成片**
   - 在 `AutoEditPlanCard` 上点击“字幕详情 / 可编辑”：
     - 容器层 `AutoEditPanel` 设置 `detailPlan`，弹出 `AutoEditDetailModal`
   - 在弹窗中修改字幕/时间轴/选片：
     - 编辑行为作用于 `detailDraft`
     - 点击“保存修改”会把该方案的覆盖写入 `customPlanById[plan_id]`
   - 在方案卡片上“按一键成片”：
     - 如果存在 `customPlanById[plan_id]`，则优先使用覆盖版本提交
     - 由 `onRealizePlan` 传给上层，最终调用后端“一键成片”接口，返回下载地址填入 `autoRealizeDownloads`。

## 三、扩展/修改建议（最佳实践）

1. **新增字段 / 修改方案 JSON 结构**
   - 优先在后端/接口类型统一修改（`AutoEditPlanApi`）
   - 前端处理：
     - 若是只读展示字段：优先修改对应视图组件（如 `AutoEditPlanCard`、`AutoEditDetailModal`），**不要**塞回 `AutoEditPanel` 容器层。
     - 若需在多个区域复用：考虑新增类似 `AutoEditBgmMixPanel` 的小组件。

2. **新增交互开关 / 表单配置项**
   - 归属“全局配置/生成参数”的，放在 `AutoEditPlannerSection`：
     - 在 `AutoEditPanelProps` 中增加 props，并下传到 `AutoEditPlannerSection`。
   - 仅作用于单个方案的，放在：
     - 列表简单展示：`AutoEditPlanCard`
     - 复杂可编辑：`AutoEditDetailModal` 中对应段落区域，直接操作 `detailDraft`。

3. **增加新的预览视图或对齐逻辑**
   - 优先在 `AutoEditPreviewPanel` 内处理：
     - 例如新增某种“对齐模式”，可以扩展 `PreviewTimeline` 或增加本地状态与切换按钮。
   - 如需要额外的数据映射（例如 clip → 其它元信息），可新增 Hook 或扩展 `useAutoEditClipMetaByPlans`。

4. **新增/调整 BGM 策略 UI**
   - 所有 BGM 相关表单都应该通过 `AutoEditBgmMixPanel` 维护：
     - 若只改文案或禁用逻辑：直接通过 `helperText / strategyLabel / policySelectDisabled` 参数配置。
     - 若要改选项内容（例如多加一个策略值）：同步调整当前 `AutoEditBgmMixPanel` 与后端字段语义，再由 `AutoEditPlannerSection` 透传。

5. **新增区域**
   - 若要给自动成片再加一个较大的 UI 区块（例如“调试信息面板”、“方案对比视图”）：
     - 建议新增一个 `AutoEditXXXSection.tsx` 文件，按照 `Planner/Candidates/DetailModal` 的模式实现
     - 在 `AutoEditPanel` 中只保留“是否渲染 + 状态/回调用于编排”的逻辑，不直接写 JSX 大块。

## 四、文件一览（按层次）

- **容器层**
  - `AutoEditPanel.tsx`
- **区域视图层**
  - `AutoEditPlannerSection.tsx`
  - `AutoEditCandidatesSection.tsx`
  - `AutoEditDetailModal.tsx`
- **子视图组件**
  - `AutoEditPreviewPanel.tsx`
  - `AutoEditPlanCard.tsx`
  - `AutoEditBgmMixPanel.tsx`
- **逻辑 & 类型**
  - `autoEditPanelHooks.ts`
  - `autoEditTypes.ts`

如后续要继续重构/扩展自动成片能力，推荐先更新本 README 中的“职责分层”与“数据流”描述，再按本结构落地代码变更，保持整个区域的长期可维护性。
