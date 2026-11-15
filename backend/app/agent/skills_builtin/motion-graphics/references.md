# references：data 属性全表 · 媒体 · 常见坑

## clip 的 data-* 属性

| 属性 | 必填 | 说明 |
|---|---|---|
| `id` | ✓ | 唯一 |
| `class="clip"` | ✓ | 声明为 clip |
| `data-start` | ✓ | 秒，或引用他 clip：`"el-1"`、`"intro + 2"` |
| `data-duration` | img/div 必须 | 视频/音频缺省取媒体时长 |
| `data-track-index` | ✓ | 整数；同轨不可重叠；不决定层叠（用 z-index） |
| `data-media-start` | 可选 | 裁剪源媒体的偏移秒 |
| `data-volume` | 可选 | 0-1，默认 1 |

子合成（已装素材块）引入：`<div data-composition-id="块id" data-composition-src="compositions/块.html" data-start data-duration data-track-index data-width data-height></div>`。

## 媒体

- `<video class="clip" src="xxx.mp4" data-start data-track-index>`：视频自带音轨时考虑 `data-volume` 压低。
- `<audio class="clip" src="bgm.mp3" data-start data-duration>`：BGM。
- 路径用相对路径（与 index.html 同目录）；外部 http 媒体渲染器会本地化，但尽量本地。

## 动画要点

- 入场用 `tl.from()`（从隐形/场外 → CSS 终位）；出场用 `tl.to()`。CSS 终位是唯一事实源。
- 同一元素避免在同一时刻 `tl.set(el,{opacity:1})` + `tl.from(el,{opacity:0})`（from 会覆盖 set）。
- 逐字/逐词动画（打字机、卡拉OK高亮）：每个字包 `<span>`，用 `tl.set()` 在算好的时间点切换，光标/装饰也用 `tl.set`（不要 CSS animation）。
- CSS animation 可用于简单循环装饰：有限 iteration-count + `animation-fill-mode: both` + 元素给 `data-start/data-duration`；复杂编排一律 GSAP。
- 音频节拍驱动：先拿 BPM/节拍点数组（外部算好写进 JS 常量），再 `tl.to(..., beatTimes[i])` 对齐。

## 常见坑

- `window.__timelines` 未注册 → 黑屏：注册名必须等于根元素 `data-composition-id`。
- 时间轴没 `paused:true` → 渲染错位（渲染器靠 seek 逐帧）。
- `data-track-index` 相同且时间重叠 → 冲突；场景换轨或错开 start。
- body 尺寸与根 `data-width/height` 不一致 → 构图偏移。
- 文字溢出：长文案手动分段成多个 clip，别指望自动换行（换行可用，但英雄帧要先验证）。
- 预览（iframe）与成片有细微时序差：以渲染产物为准；重要项目 draft 档先渲一次验收。

## 渲染参数

- `fps`：口播/花字 30；滑顺运动 60（渲染时间翻倍）。
- `quality`：迭代用 draft（快），交付用 standard/high。
- 渲染耗时经验：1080×1920@30fps 约 1 秒成片 ≈ 1-3 分钟（机器而异），先告诉用户预期。
