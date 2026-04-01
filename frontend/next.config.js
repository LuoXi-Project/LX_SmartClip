/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV === 'development'

const nextConfig = {
  reactStrictMode: true,
  // 仅在生产构建时启用静态导出；开发模式需要 Next server 才能支持 rewrites。
  output: process.env.NODE_ENV === 'production' ? 'export' : undefined,
  ...(isDev
    ? {
        async rewrites() {
          // 开发模式下把 /api/* /storage/* 转发到后端，
          // 保证使用相对路径时也能直接请求到 FastAPI。
          const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
          return [
            { source: '/api/:path*', destination: `${api}/api/:path*` },
            { source: '/storage/:path*', destination: `${api}/storage/:path*` },
          ]
        },
      }
    : {}),
}

module.exports = nextConfig
