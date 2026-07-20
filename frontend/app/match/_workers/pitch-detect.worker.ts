/// <reference lib="webworker" />
/**
 * 音高轨识别 Worker：在后台线程跑自相关（autocorrelation），
 * 避免双层 for 循环阻塞主线程导致页面卡死。
 *
 * 算法与原主线程实现完全一致，仅迁移执行环境：
 * - 输入：{ data: Float32Array (单声道 PCM), sampleRate: number }
 * - 输出：number[]（每帧音高 Hz，0 表示无声/无音高）
 */
interface PitchWorkerRequest {
  data: Float32Array
  sampleRate: number
}

self.onmessage = (e: MessageEvent<PitchWorkerRequest>) => {
  const { data, sampleRate: sr } = e.data
  if (!data || !data.length || !sr) {
    ;(self as unknown as Worker).postMessage([])
    return
  }

  const hop = Math.max(128, Math.floor(sr * 0.02))
  const minHz = 70
  const maxHz = 320
  const minLag = Math.floor(sr / maxHz)
  const maxLag = Math.floor(sr / minHz)
  const out: number[] = []

  for (let i = 0; i + maxLag < data.length; i += hop) {
    // 能量过低直接判无音高
    let sum = 0
    const end = Math.min(data.length, i + hop)
    for (let j = i; j < end; j += 1) sum += data[j] * data[j]
    const rms = Math.sqrt(sum / Math.max(1, end - i))
    if (rms < 0.01) {
      out.push(0)
      continue
    }
    let bestLag = 0
    let best = 0
    for (let lag = minLag; lag <= maxLag; lag += 1) {
      let c = 0
      for (let j = 0; j < hop; j += 1) c += data[i + j] * data[i + j + lag]
      if (c > best) {
        best = c
        bestLag = lag
      }
    }
    const hz = bestLag > 0 ? sr / bestLag : 0
    out.push(hz >= minHz && hz <= maxHz ? hz : 0)
  }

  ;(self as unknown as Worker).postMessage(out)
}
