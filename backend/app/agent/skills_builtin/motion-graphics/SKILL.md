---
name: 动效合成（HyperFrames）
description: 用 HTML 写动效视频（标题卡/片头/VFX/带动效字幕）渲染成 MP4。当用户要标题卡、片头片尾、动效字幕、VFX 短片、节目花字、文字动画时使用；先 load 本技能再写合成。
---

# HyperFrames 动效合成

HTML 即视频源码：一个合成 = 一个 HTML 文件，`data-*` 属性声明时序，GSAP 暂停时间轴声明动画，渲染器逐帧确定性输出 MP4。

## 工作流（固定顺序）

1. **先想清楚再写**：叙事弧（几个场景、情绪节奏）、每个场景的「英雄帧」（元素最多最清晰的那一帧）、进出场时序。
2. **布局先于动画**：先把每个元素用静态 CSS 摆在「英雄帧」位置（容器 `width/height:100%` + padding 布局，禁止内容容器用 absolute 定位），再写入场动画 `tl.from(...)`（从场外/隐形 → CSS 位置）、出场 `tl.to(...)`。
3. **preview_composition 预览** → 让用户看画布里的实时预览，不满意就改。
4. **render_composition 渲染**（draft 试渲 → standard 定稿更省时）。

## 合成骨架（照抄这个结构）

```html
<!doctype html>
<html><head><meta charset="UTF-8"/>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<style>
  html,body{margin:0;width:1080px;height:1920px;overflow:hidden;background:#0b1020}
  #root{width:100%;height:100%;display:flex;align-items:center;justify-content:center}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="5"
     data-width="1080" data-height="1920">
  <h1 id="title" class="clip" data-start="0" data-duration="5" data-track-index="0">标题</h1>
</div>
<script>
const tl = gsap.timeline({ paused: true });
tl.fromTo("#title",{opacity:0,y:80},{opacity:1,y:0,duration:.5,ease:"power3.out"},0);
window.__timelines["main"] = tl; tl.seek(0);
</script>
</body></html>
```

## 硬性规则（违反=渲染废片）

- 时长以**最长 clip 的 data-start+data-duration**为准；场景切换用多个 clip 的 start/duration 编排。
- 每个 clip 必须有：`id`、`class="clip"`、`data-start`、`data-duration`、`data-track-index`（同轨不可重叠；层叠用 z-index）。
- 时间轴必须 `paused:true`，注册到 `window.__timelines["main"]`（id 与根元素 data-composition-id 一致），末尾 `tl.seek(0)`。
- 禁止 `Math.random()` / `Date.now()` / `requestAnimationFrame` / CSS 无限动画（不确定帧 = 每次渲染不同）；随机用种子化 PRNG。
- 竖屏 1080×1920（抖音/快手），横屏 1920×1080；文字移动端最小 96px（等宽字体可 64-72px）。
- 字体只用系统安全字体或显式 font-family 栈；重要文字用 text-shadow/-webkit-text-stroke 保对比度。

## 内容创作原则

- 用户只说「做个标题卡」时不要自作主张加 3 个场景 + BGM；提案可以，直接加不行。
- 开放式需求（做个片头）先问清：平台（竖/横屏）、时长、气质（高级感/综艺感/科技感），或给 2 个方向变体。
- 颜色不要默认 #333/#3b82f6/Roboto——按内容定调色板并写 CSS 变量。

进阶（视频片段、音频、逐字卡拉OK、data 属性全表与常见坑）见 references。
