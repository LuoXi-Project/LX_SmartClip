import type {
  ScriptStockOnlineProvider,
  ScriptStockPexelsCacheItemApi,
  ScriptStockPexelsImageApi,
  ScriptStockPexelsVideoApi,
  ScriptStockPixabayCacheItemApi,
  ScriptStockPixabayImageApi,
  ScriptStockPixabayVideoApi,
  ScriptStockUnsplashCacheItemApi,
  ScriptStockUnsplashPhotoApi,
} from '@/lib/api'

export type StockSourceTab = 'local' | ScriptStockOnlineProvider

export type StockSegState = {
  id: string
  text: string
  sourceTab: StockSourceTab
  searchQuery: string
  localVideoIds: string[]
  libraryTrimSlots?: import('./types').ClipTrimRange[]
  pexelsResults: ScriptStockPexelsVideoApi[]
  pexelsImageResults: ScriptStockPexelsImageApi[]
  pixabayResults: ScriptStockPixabayVideoApi[]
  pixabayImageResults: ScriptStockPixabayImageApi[]
  unsplashResults: ScriptStockUnsplashPhotoApi[]
  searching: boolean
  /** `${provider}:${id}` */
  downloadingKey: string | null
  pexelsStoredRelPaths: string[]
  pixabayStoredRelPaths: string[]
  unsplashStoredRelPaths: string[]
}

export type StockCacheItem =
  | ScriptStockPexelsCacheItemApi
  | ScriptStockPixabayCacheItemApi
  | ScriptStockUnsplashCacheItemApi

export function newStockSeg(text: string): StockSegState {
  return {
    id: `ss_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
    text,
    sourceTab: 'pexels',
    searchQuery: '',
    localVideoIds: [],
    libraryTrimSlots: undefined,
    pexelsResults: [],
    pexelsImageResults: [],
    pixabayResults: [],
    pixabayImageResults: [],
    unsplashResults: [],
    searching: false,
    downloadingKey: null,
    pexelsStoredRelPaths: [],
    pixabayStoredRelPaths: [],
    unsplashStoredRelPaths: [],
  }
}

export function storedRelPathsForProvider(seg: StockSegState, provider: ScriptStockOnlineProvider): string[] {
  if (provider === 'pexels') return seg.pexelsStoredRelPaths
  if (provider === 'pixabay') return seg.pixabayStoredRelPaths
  return seg.unsplashStoredRelPaths
}

export function onlineProviderLabel(p: ScriptStockOnlineProvider): string {
  if (p === 'pexels') return 'Pexels'
  if (p === 'pixabay') return 'Pixabay'
  return 'Unsplash'
}

export function downloadKey(
  provider: ScriptStockOnlineProvider,
  mediaType: 'image' | 'video',
  id: string | number,
): string {
  return `${provider}:${mediaType}:${id}`
}
