'use client'

import { useEffect, useState } from 'react'
import { useAppStore, type Video } from '@/lib/store'
import apiClient from '@/lib/api'
import { Upload, Trash2, Play, Calendar, Film } from 'lucide-react'

export default function LibraryPage() {
  const { videos, setVideos, addVideo, removeVideo } = useAppStore()
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [dragActive, setDragActive] = useState(false)

  // 加载视频列表
  useEffect(() => {
    const fetchVideos = async () => {
      try {
        setLoading(true)
        const data = await apiClient.get('/api/videos')
        setVideos(data || [])
      } catch (error) {
        console.error('Failed to fetch videos:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchVideos()
  }, [setVideos])

  // 处理文件上传
  const handleUpload = async (files: FileList) => {
    if (!files || files.length === 0) return

    setUploading(true)
    for (const file of Array.from(files)) {
      try {
        const formData = new FormData()
        formData.append('file', file)

        const response = await apiClient.post('/api/videos/upload', formData, {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        })

        addVideo({
          id: response.id,
          name: response.name,
          file_path: '',
          duration: null,
          total_clips: 0,
          split_mode: 'scene',
          status: 'pending',
          upload_at: response.upload_at,
        })
      } catch (error) {
        console.error('Upload failed:', error)
        alert(`上传失败: ${file.name}`)
      }
    }
    setUploading(false)
  }

  // 处理删除
  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个视频吗？')) return

    try {
      await apiClient.delete(`/api/videos/${id}`)
      removeVideo(id)
    } catch (error) {
      console.error('Delete failed:', error)
      alert('删除失败')
    }
  }

  // 拖拽处理
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    handleUpload(e.dataTransfer.files)
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2 text-slate-100">素材库</h1>
          <p className="text-slate-400">管理和处理您的视频素材</p>
        </div>

        {/* Upload Area */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`mb-8 border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            dragActive
              ? 'border-blue-400 bg-blue-500/10'
              : 'border-slate-600 bg-slate-800/30'
          }`}
        >
          <Upload className="w-12 h-12 mx-auto mb-4 text-slate-400" />
          <h2 className="text-xl font-semibold text-slate-100 mb-2">
            拖拽视频文件到此处
          </h2>
          <p className="text-slate-400 mb-4">或点击下方按钮选择文件</p>
          <label className="inline-block">
            <input
              type="file"
              multiple
              accept="video/*"
              onChange={(e) => e.target.files && handleUpload(e.target.files)}
              disabled={uploading}
              className="hidden"
            />
            <span className="inline-block px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer transition-colors disabled:opacity-50">
              {uploading ? '上传中...' : '选择文件'}
            </span>
          </label>
        </div>

        {/* Videos Grid */}
        {loading ? (
          <div className="text-center py-12">
            <div className="inline-block w-8 h-8 border-4 border-slate-600 border-t-blue-400 rounded-full animate-spin"></div>
            <p className="text-slate-400 mt-4">加载中...</p>
          </div>
        ) : videos.length === 0 ? (
          <div className="text-center py-12">
            <Film className="w-16 h-16 mx-auto text-slate-600 mb-4" />
            <p className="text-slate-400">还没有上传任何视频</p>
          </div>
        ) : (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {videos.map((video) => (
              <div
                key={video.id}
                className="bg-slate-800/50 backdrop-blur border border-slate-700 rounded-lg overflow-hidden hover:border-blue-500/50 transition-colors group"
              >
                {/* Thumbnail */}
                <div className="relative bg-slate-900 aspect-video flex items-center justify-center overflow-hidden">
                  <Play className="w-12 h-12 text-slate-600 group-hover:text-blue-400 transition-colors" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
                </div>

                {/* Info */}
                <div className="p-4">
                  <h3 className="font-semibold text-slate-100 truncate mb-2">
                    {video.name}
                  </h3>

                  {/* Status Badge */}
                  <div className="mb-3">
                    <span
                      className={`inline-block px-2 py-1 text-xs rounded-full ${
                        video.status === 'pending'
                          ? 'bg-yellow-500/20 text-yellow-300'
                          : video.status === 'processing'
                            ? 'bg-blue-500/20 text-blue-300'
                            : video.status === 'done'
                              ? 'bg-green-500/20 text-green-300'
                              : 'bg-red-500/20 text-red-300'
                      }`}
                    >
                      {video.status === 'pending'
                        ? '待处理'
                        : video.status === 'processing'
                          ? '处理中'
                          : video.status === 'done'
                            ? '已完成'
                            : '错误'}
                    </span>
                  </div>

                  {/* Meta */}
                  <div className="space-y-1 text-sm text-slate-400 mb-4">
                    <div className="flex items-center gap-2">
                      <Calendar className="w-4 h-4" />
                      <span>
                        {new Date(video.upload_at).toLocaleDateString('zh-CN')}
                      </span>
                    </div>
                    {video.total_clips > 0 && (
                      <div className="flex items-center gap-2">
                        <Film className="w-4 h-4" />
                        <span>{video.total_clips} 个片段</span>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2">
                    <button className="flex-1 px-3 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 transition-colors">
                      处理
                    </button>
                    <button
                      onClick={() => handleDelete(video.id)}
                      className="px-3 py-2 bg-red-600/20 text-red-400 text-sm rounded hover:bg-red-600/30 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
