import { API_BASE_URL } from '@/lib/runtime-config'

/** 将后端返回的相对 storage URL 转为浏览器可访问的完整地址 */
export function resolveStorageUrl(url: string | undefined | null): string {
  const raw = (url || '').trim()
  if (!raw) return ''
  if (raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('file://')) {
    return raw
  }
  const base = (API_BASE_URL || '').replace(/\/$/, '')
  return `${base}${raw.startsWith('/') ? raw : `/${raw}`}`
}

export const resolveStudioMediaUrl = resolveStorageUrl

export function isVideoExport(payload: Record<string, unknown>): boolean {
  const kind = String(payload.kind || '')
  if (kind === 'video') return true
  if (kind === 'jianying') return false
  const fn = String(payload.filename || '').toLowerCase()
  return fn.endsWith('.mp4') || fn.endsWith('.webm') || fn.endsWith('.mov')
}

export function isJianyingExport(payload: Record<string, unknown>): boolean {
  return String(payload.kind || '') === 'jianying'
}

export function payloadToExportArtifact(
  payload: Record<string, unknown>
): { type: 'export'; id: string; payload: Record<string, unknown> } {
  return {
    type: 'export',
    id: String(payload.filename || payload.url || 'export'),
    payload,
  }
}
