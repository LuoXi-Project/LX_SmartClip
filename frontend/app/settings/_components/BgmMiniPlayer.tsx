'use client'

import { useEffect, useId, useRef, useState } from 'react'
import AudioPlayer, { RHAP_UI } from 'react-h5-audio-player'
import { Download } from 'lucide-react'
import clsx from 'clsx'
import 'react-h5-audio-player/lib/styles.css'
import './bgm-audio-player.css'

const RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] as const

export type BgmMiniPlayerProps = {
  src: string
  /** 下载时建议的文件名（同域 URL 时浏览器才会稳定使用该名） */
  downloadFilename?: string
  className?: string
}

type PlayerInstance = InstanceType<typeof AudioPlayer>

export function BgmMiniPlayer({ src, downloadFilename, className }: BgmMiniPlayerProps) {
  const playerRef = useRef<PlayerInstance>(null)
  const [rate, setRate] = useState(1)
  const rateId = useId()

  useEffect(() => {
    setRate(1)
  }, [src])

  useEffect(() => {
    const a = playerRef.current?.audio.current
    if (a) a.playbackRate = rate
  }, [rate, src])

  const handlePlay = (e: Event) => {
    const el = e.currentTarget as HTMLAudioElement
    document.querySelectorAll<HTMLAudioElement>('.bgm-rhap-player audio').forEach((a) => {
      if (a !== el) a.pause()
    })
  }

  return (
    <AudioPlayer
      ref={playerRef}
      src={src}
      preload="metadata"
      autoPlay={false}
      autoPlayAfterSrcChange={false}
      showJumpControls
      showFilledVolume
      progressJumpSteps={{ backward: 10000, forward: 10000 }}
      layout="stacked"
      className={clsx('bgm-rhap-player', className)}
      onPlay={handlePlay}
      customAdditionalControls={[
        <div key="bgm-tools" className="flex items-center gap-1.5 flex-wrap">
          <select
            id={rateId}
            aria-label="播放倍速"
            value={rate}
            onChange={(e) => setRate(Number(e.target.value))}
            className="rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-[11px] text-slate-200 outline-none focus:border-indigo-500"
          >
            {RATES.map((r) => (
              <option key={r} value={r}>
                {r === 1 ? '1× 常速' : `${r}×`}
              </option>
            ))}
          </select>
          <a
            href={src}
            download={downloadFilename || undefined}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-slate-600 bg-slate-900 text-slate-300 transition hover:bg-slate-800 hover:text-white"
            title="下载音频"
            aria-label="下载音频"
          >
            <Download className="h-3.5 w-3.5" strokeWidth={2} />
          </a>
        </div>,
        RHAP_UI.LOOP,
      ]}
    />
  )
}
