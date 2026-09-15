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
  ScriptStockMixkitCacheItemApi,
  ScriptStockMixkitVideoApi,
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
  mixkitResults: ScriptStockMixkitVideoApi[]
  searching: boolean
  /** `${provider}:${id}` */
  downloadingKey: string | null
  pexelsStoredRelPaths: string[]
  pixabayStoredRelPaths: string[]
  unsplashStoredRelPaths: string[]
  coverrStoredRelPaths: string[]
  mixkitStoredRelPaths: string[]
}

export type StockCacheItem =
  | ScriptStockPexelsCacheItemApi
  | ScriptStockPixabayCacheItemApi
  | ScriptStockUnsplashCacheItemApi
  | ScriptStockCoverrCacheItemApi
  | ScriptStockMixkitCacheItemApi

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
    mixkitResults: [],
    searching: false,
    downloadingKey: null,
    pexelsStoredRelPaths: [],
    pixabayStoredRelPaths: [],
    unsplashStoredRelPaths: [],
    coverrStoredRelPaths: [],
    mixkitStoredRelPaths: [],
  }
}

export function storedRelPathsForProvider(seg: StockSegState, provider: ScriptStockOnlineProvider): string[] {
  if (provider === 'pexels') return seg.pexelsStoredRelPaths
  if (provider === 'pixabay') return seg.pixabayStoredRelPaths
  if (provider === 'unsplash') return seg.unsplashStoredRelPaths
  if (provider === 'coverr') return seg.coverrStoredRelPaths
  return seg.mixkitStoredRelPaths
}

export function onlineProviderLabel(p: ScriptStockOnlineProvider): string {
  if (p === 'pexels') return 'Pexels'
  if (p === 'pixabay') return 'Pixabay'
  if (p === 'unsplash') return 'Unsplash'
  if (p === 'coverr') return 'Coverr'
  return 'Mixkit'
}

export function downloadKey(
  provider: ScriptStockOnlineProvider,
  mediaType: 'image' | 'video',
  id: string | number,
): string {
  return `${provider}:${mediaType}:${id}`
}
