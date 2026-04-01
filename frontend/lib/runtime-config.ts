// 前端运行时配置（统一入口）
// - 默认空字符串：表示同域使用相对路径
// - 可通过 `.env.local` 的 `NEXT_PUBLIC_API_URL` 覆盖（需以 NEXT_PUBLIC_ 开头才能暴露给浏览器）

export const API_BASE_URL: string = (process.env.NEXT_PUBLIC_API_URL || '').trim()

