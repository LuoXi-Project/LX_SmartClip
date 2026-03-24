'use client'

import { useEffect, useState } from 'react'
import { useAppStore } from '@/lib/store'
import apiClient from '@/lib/api'
import { Activity, AlertCircle, CheckCircle } from 'lucide-react'

export default function Home() {
  const { backendStatus, setBackendStatus } = useAppStore()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const checkBackendHealth = async () => {
      try {
        setLoading(true)
        const data = await apiClient.get<unknown, { status: string }>('/health')
        if (data && data.status === 'ok') {
          setBackendStatus('connected')
        } else {
          setBackendStatus('disconnected')
        }
      } catch (error) {
        console.error('Backend health check failed:', error)
        setBackendStatus('disconnected')
      } finally {
        setLoading(false)
      }
    }

    checkBackendHealth()
    const interval = setInterval(async () => {
      if (useAppStore.getState().backendStatus === 'connected') {
        clearInterval(interval)
        return
      }
      await checkBackendHealth()
    }, 5000)
    return () => clearInterval(interval)
  }, [setBackendStatus])

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="container mx-auto px-4 py-16">
        {/* Header */}
        <div className="text-center mb-16">
          <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
            LX SmartClip
          </h1>
          <p className="text-xl text-slate-300 mb-2">
            本地轻量化 AI 智能素材匹配剪辑工具
          </p>
          <p className="text-slate-400">
            批量素材入库 → 多模式切分 → 多模态理解 → 三级精准匹配 → TTS 配音 → 导出工程
          </p>
        </div>

        {/* Status Card */}
        <div className="max-w-md mx-auto mb-12">
          <div className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-slate-100">系统状态</h2>
              <Activity className="w-5 h-5 text-blue-400" />
            </div>

            {loading ? (
              <div className="flex items-center gap-3 text-slate-300">
                <div className="w-3 h-3 bg-yellow-400 rounded-full animate-pulse"></div>
                <span>检查中...</span>
              </div>
            ) : backendStatus === 'connected' ? (
              <div className="flex items-center gap-3 text-green-400">
                <CheckCircle className="w-5 h-5" />
                <span>后端已连接</span>
              </div>
            ) : (
              <div className="flex items-center gap-3 text-red-400">
                <AlertCircle className="w-5 h-5" />
                <span>后端未连接</span>
              </div>
            )}

            <p className="text-sm text-slate-400 mt-4">
              API 地址: {process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}
            </p>
          </div>
        </div>

        {/* Features Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 max-w-5xl mx-auto">
          {[
            {
              title: '素材库',
              description: '上传、管理、预览视频素材',
              icon: '📹',
            },
            {
              title: '智能切分',
              description: '镜头识别 / 固定时长双模式',
              icon: '✂️',
            },
            {
              title: '多模态理解',
              description: 'ASR + VLM 自动分析',
              icon: '🧠',
            },
            {
              title: '三级匹配',
              description: 'RAG 初筛 → LLM 精排 → 人工选择',
              icon: '🎯',
            },
            {
              title: 'TTS 配音',
              description: '自动生成高质量配音',
              icon: '🎙️',
            },
            {
              title: '工程导出',
              description: '导出剪辑工程文件',
              icon: '📦',
            },
          ].map((feature, idx) => (
            <div
              key={idx}
              className="bg-slate-800/30 backdrop-blur border border-slate-700 rounded-lg p-6 hover:border-blue-500/50 transition-colors"
            >
              <div className="text-3xl mb-3">{feature.icon}</div>
              <h3 className="font-semibold text-slate-100 mb-2">
                {feature.title}
              </h3>
              <p className="text-sm text-slate-400">{feature.description}</p>
            </div>
          ))}
        </div>

        {/* CTA */}
        <div className="text-center mt-16">
          <a
            href="/library"
            className="inline-block px-8 py-3 bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold rounded-lg hover:shadow-lg hover:shadow-blue-500/50 transition-all"
          >
            开始使用
          </a>
        </div>
      </div>
    </main>
  )
}
