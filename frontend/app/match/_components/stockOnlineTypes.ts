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
  ScriptStockCoverrCacheItemApi,
  ScriptStockCoverrVideoApi,
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
  coverrResults: ScriptStockCoverrVideoApi[]
  searching: boolean
  /** `${provider}:${id}` */
  downloadingKey: string | null
  pexelsStoredRelPaths: string[]
  pixabayStoredRelPaths: string[]
  unsplashStoredRelPaths: string[]
  coverrStoredRelPaths: string[]
}

export type StockCacheItem =
  | ScriptStockPexelsCacheItemApi
  | ScriptStockPixabayCacheItemApi
  | ScriptStockUnsplashCacheItemApi
  | ScriptStockCoverrCacheItemApi

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
    coverrResults: [],
    searching: false,
    downloadingKey: null,
    pexelsStoredRelPaths: [],
    pixabayStoredRelPaths: [],
    unsplashStoredRelPaths: [],
    coverrStoredRelPaths: [],
  }
}

export function storedRelPathsForProvider(seg: StockSegState, provider: ScriptStockOnlineProvider): string[] {
  if (provider === 'pexels') return seg.pexelsStoredRelPaths
  if (provider === 'pixabay') return seg.pixabayStoredRelPaths
  if (provider === 'unsplash') return seg.unsplashStoredRelPaths
  return seg.coverrStoredRelPaths
}

export function onlineProviderLabel(p: ScriptStockOnlineProvider): string {
  if (p === 'pexels') return 'Pexels'
  if (p === 'pixabay') return 'Pixabay'
  if (p === 'unsplash') return 'Unsplash'
  return 'Coverr'
}

export function downloadKey(
  provider: ScriptStockOnlineProvider,
  mediaType: 'image' | 'video',
  id: string | number,
): string {
  return `${provider}:${mediaType}:${id}`
}
