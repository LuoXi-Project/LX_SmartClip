'use client'

import { ImageIcon, Save } from 'lucide-react'

import { STOCK_MEDIA_KEYS } from './constants'
import { ConfigField } from './ConfigField'
import { SaveBtn } from './SaveBtn'
import type { ConfigMap } from './types'

interface Props {
  config: ConfigMap
  edits: Record<string, string>
  saving: Record<string, boolean>
  saved: Record<string, boolean>
  onSet: (key: string, value: string) => void
  onSave: (key: string) => void
  onSaveGroup: (keys: string[]) => void
}

const PARAM_HINTS: Record<string, string> = {
  pexels_api_key:
    '在 Pexels 申请免费 API Key；用于「智能剪辑 → 文案素材成片」搜索并下载无版权短视频，文件存放在 stock_media/pexels',
  pixabay_api_key:
    '在 Pixabay 申请免费 API Key；用于文案素材成片搜索/下载视频，文件存放在 stock_media/pixabay（见 https://pixabay.com/api/docs/ ）',
  unsplash_access_key:
    '在 Unsplash Developers 注册应用获取 Access Key；用于搜索高清图片并自动转为静音短视频，文件存放在 stock_media/unsplash',
  coverr_api_key:
    'Coverr 视频 API Key；用于文案素材成片搜索/下载无版权短视频，文件存放在 stock_media/coverr（见 https://api.coverr.co/docs/videos/ ）',
  stock_media_http_proxy:
    '可选。留空时 Pexels / Pixabay / Unsplash / Coverr / Mixkit 请求直连外网，不受本机系统代理（HTTP_PROXY）影响；需走代理时再填，如 http://127.0.0.1:7890',
}

const KEY_LINKS: Record<string, { label: string; href: string }> = {
  pexels_api_key: { label: 'Pexels API', href: 'https://www.pexels.com/api/' },
  pixabay_api_key: { label: 'Pixabay API', href: 'https://pixabay.com/api/docs/' },
  unsplash_access_key: { label: 'Unsplash Developers', href: 'https://unsplash.com/developers' },
  coverr_api_key: { label: 'Coverr API', href: 'https://api.coverr.co/docs/videos/' },
}

export function StockMediaSection({ config, edits, saving, saved, onSet, onSave, onSaveGroup }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = STOCK_MEDIA_KEYS.some((k) => isDirty(k) && config[k])
  const visibleKeys = STOCK_MEDIA_KEYS.filter((k) => config[k])

  if (!visibleKeys.length) return null

  return (
    <section
      id="stock-media"
      className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden scroll-mt-28"
    >
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100 flex items-center gap-2">
            <ImageIcon className="w-5 h-5 text-sky-400" />
            在线素材（文案成片）
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            与视频切片无关；配置后可在「智能剪辑 → 文案素材成片」使用 Pexels、Pixabay、Unsplash、Coverr、Mixkit
          </p>
        </div>
        {groupDirty && (
          <button
            type="button"
            onClick={() => onSaveGroup(STOCK_MEDIA_KEYS)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
          >
            <Save className="w-3.5 h-3.5" />
            保存全部
          </button>
        )}
      </div>

      <div className="px-6 py-5 space-y-4">
        <p className="text-[11px] text-slate-500 leading-relaxed rounded-lg border border-slate-700/80 bg-slate-950/40 px-3 py-2.5">
          各平台密钥独立保存；未配置的平台在成片页搜索时会提示到此设置。Pexels / Pixabay 支持视频与图片；图片仅存本地，成片时按段时长静帧。多图默认均分该段时长。Mixkit
          无官方 API、无需密钥，走页面抓取（不稳定时可在下方配置代理）。HTTP
          代理留空即可直连，避免本机全局代理导致 502；仅在无法直连外网时再填写。
        </p>
        {visibleKeys.map((key) => {
          const link = KEY_LINKS[key]
          return (
            <div key={key} className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-xs text-slate-400">{config[key].label || key}</label>
                {link ? (
                  <a
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] text-sky-400 hover:underline"
                  >
                    {link.label} →
                  </a>
                ) : null}
              </div>
              {PARAM_HINTS[key] && <p className="text-xs text-slate-500">{PARAM_HINTS[key]}</p>}
              <div className="flex gap-2">
                <div className="flex-1">
                  <ConfigField cfgKey={key} item={config[key]} value={v(key)} onChange={(val) => onSet(key, val)} />
                </div>
                <SaveBtn
                  dirty={isDirty(key)}
                  saving={!!saving[key]}
                  saved={!!saved[key]}
                  onSave={() => onSave(key)}
                />
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
