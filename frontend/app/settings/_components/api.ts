import apiClient from '@/lib/api'

export async function fetchModels(baseUrl: string, apiKey: string): Promise<string[]> {
  const data = await apiClient.post<unknown, { models: string[] }>('/api/config/models', {
    base_url: baseUrl,
    api_key: apiKey,
  })
  return Array.isArray(data?.models) ? data.models : []
}
