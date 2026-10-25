/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV === 'development'

const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['three'],
  // 仅在生产构建时启用静态导出；开发模式需要 Next server 才能支持 rewrites。
  output: process.env.NODE_ENV === 'production' ? 'export' : undefined,
  ...(isDev
    ? {
        async rewrites() {
          // 开发模式下把 /api/* /storage/* 转发到后端，
          // 保证使用相对路径时也能直接请求到 FastAPI。
          // 注意用 127.0.0.1 而非 localhost：Windows 上 Node 可能把 localhost
          // 解析为 IPv6 ::1，而后端默认只绑 127.0.0.1，会导致 dev 代理全部 500。
          const api = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'
          return [
            { source: '/health', destination: `${api}/health` },
            { source: '/api/:path*', destination: `${api}/api/:path*` },
            { source: '/storage/:path*', destination: `${api}/storage/:path*` },
          ]
        },
      }
    : {}),
}

module.exports = nextConfig
