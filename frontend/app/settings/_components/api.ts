import apiClient from '@/lib/api'

export async function fetchModels(
  baseUrl: string,
  apiKey: string,
  opts?: { signal?: AbortSignal },
): Promise<string[]> {
  const data = await apiClient.post<unknown, { models: string[] }>('/api/config/models', {
    base_url: baseUrl,
    api_key: apiKey,
  }, {
    // axios 支持 AbortSignal（浏览器/Node 环境均可）
    signal: opts?.signal,
  })
  return Array.isArray(data?.models) ? data.models : []
}
