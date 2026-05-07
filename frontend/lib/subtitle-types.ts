export interface SubtitleStyle {
  font_name: string
  font_size: number
  font_color: string
  outline_color: string
  outline_width: number
  shadow: number
  bold: boolean
  italic: boolean
  position: 'bottom' | 'top' | 'center'
  margin_v: number
  pos_x_pct: number
  pos_y_pct: number
  background: boolean
  background_pad_x: number
  background_pad_y: number
  background_opacity: number
  max_chars_per_line: number
}

export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  font_name: 'Arial',
  font_size: 56,
  font_color: '#FFFFFF',
  outline_color: '#000000',
  outline_width: 2,
  shadow: 1,
  bold: false,
  italic: false,
  position: 'bottom',
  margin_v: 20,
  pos_x_pct: 50,
  pos_y_pct: 90,
  background: true,
  background_pad_x: 6,
  background_pad_y: 3,
  background_opacity: 55,
  max_chars_per_line: 20,
}

export type ExportMode =
  | 'zip'
  | 'subtitle'
  | 'original'
  /** 仅剪映草稿 ZIP（TTS 时间轴），不导出 MP4 */
  | 'jianying_tts'
  /** 仅剪映草稿 ZIP（原声时间轴），不导出 MP4 */
  | 'jianying_original'