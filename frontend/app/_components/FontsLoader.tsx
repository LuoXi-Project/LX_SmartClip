'use client'

/**
 * 非阻塞字体加载器
 *
 * 背景：直接写 <link rel="stylesheet" href="...fonts.loli.net..."> 是渲染阻塞资源，
 * CDN 卡死/超时会导致整页白屏。
 *
 * 方案：用 media="print" + onLoad 切回 all 的经典模式，让字体加载不再阻塞首屏渲染。
 * - media="print"：浏览器仍下载该样式表，但不阻塞屏幕渲染，首屏立刻用系统字体显示
 * - onLoad：下载完成后把 media 切回 all，字体静默生效
 * - 失败/超时：onLoad 不触发，页面继续用系统字体，绝不再白屏
 */
export default function FontsLoader() {
  const href =
    'https://fonts.loli.net/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&family=JetBrains+Mono:wght@400;500&display=swap'

  return (
    <>
      <link rel="preconnect" href="https://fonts.loli.net" crossOrigin="anonymous" />
      <link
        rel="stylesheet"
        href={href}
        media="print"
        onLoad={(e) => {
          ;(e.currentTarget as HTMLLinkElement).media = 'all'
        }}
      />
      <noscript>
        <link rel="stylesheet" href={href} />
      </noscript>
    </>
  )
}
