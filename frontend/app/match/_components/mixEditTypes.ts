/** 混剪顶层音轨模式 */
export type MixAudioMode = 'keep_original' | 'mute_all_original'

/** 模式一：多人声混合策略 */
export type VoiceMergeStrategy = 'strict_single' | 'same_voice_concat'

/** 模式二：成片音轨 */
export type MuteAudioTrack = 'ai_tts_asr' | 'ai_tts_llm' | 'bgm_only'
