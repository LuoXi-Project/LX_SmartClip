#!/usr/bin/env node
/**
 * LX SmartClip × HyperFrames 渲染桥。
 *
 * 用法：
 *   node render.mjs --project <dir> --output <mp4> [--fps 30] [--quality standard|draft|high]
 *
 * 环境变量：
 *   HF_PRODUCER_ENTRY   producer 的 dist/index.js 绝对路径（打包版 node_modules 不在本目录时用）
 *   HF_CHROME_PATH      Chromium 可执行文件（缺省让 producer 自行解析）
 *   HYPERFRAMES_FFMPEG_PATH / HYPERFRAMES_FFPROBE_PATH  由 Python 侧注入
 *
 * 输出：stdout 每行一个 JSON（进度/完成/失败），供 Python 侧解析上报 job。
 * 退出码：0 = completed（含 completed_with_warnings），1 = 失败/取消。
 */
import { pathToFileURL } from "node:url";

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

const projectDir = arg("--project");
const outputPath = arg("--output");
const fps = Number(arg("--fps", "30"));
const quality = arg("--quality", "standard");
const format = arg("--format", "mp4");

if (!projectDir || !outputPath) {
  emit({ t: "error", error: "需要 --project 与 --output 参数" });
  process.exit(1);
}

let producer;
try {
  if (process.env.HF_PRODUCER_ENTRY) {
    producer = await import(pathToFileURL(process.env.HF_PRODUCER_ENTRY).href);
  } else {
    producer = await import("@hyperframes/producer");
  }
} catch (e) {
  emit({ t: "error", error: `加载 @hyperframes/producer 失败：${e?.message || e}` });
  process.exit(1);
}

const config = {
  fps,
  quality,
};
if (format && format !== "mp4") {
  config.format = format;
}
if (process.env.HF_CHROME_PATH) {
  config.producerConfig = { chromePath: process.env.HF_CHROME_PATH };
}

const job = producer.createRenderJob(config);

emit({
  t: "start",
  renderId: job.id,
  totalFrames: job.totalFrames ?? null,
});

try {
  await producer.executeRenderJob(job, projectDir, outputPath, (j, message) => {
    emit({
      t: "progress",
      status: j.status,
      progress: typeof j.progress === "number" ? j.progress : null,
      framesRendered: j.framesRendered ?? null,
      totalFrames: j.totalFrames ?? null,
      message: message ? String(message).slice(0, 200) : null,
    });
  });
} catch (e) {
  emit({
    t: "error",
    error: String(e?.message || e).slice(0, 2000),
    failedStage: job.failedStage ?? null,
  });
  process.exit(1);
}

const ok = job.outcome === "completed" || job.outcome === "completed_with_warnings";
emit({
  t: ok ? "done" : "error",
  status: job.status,
  outcome: job.outcome ?? null,
  duration: job.duration ?? null,
  totalFrames: job.totalFrames ?? null,
  warnings: (job.warnings || []).slice(0, 5).map((w) => String(w?.message || w).slice(0, 200)),
  error: job.error ?? null,
});
process.exit(ok ? 0 : 1);
