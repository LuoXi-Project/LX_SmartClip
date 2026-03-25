export interface ConfigItem {
  value: string
  type: string
  label: string
  options: string | null
}

export type ConfigMap = Record<string, ConfigItem>

export interface ProviderPreset {
  id: string
  name: string
  logo: string
  baseUrl: string
  defaultModel?: string
}
