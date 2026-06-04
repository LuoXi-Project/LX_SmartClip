/** 与 backend export_intent.py 对齐，用于前端无响应时的提示 */

const REALIZE_RE =
  /按当前方案成片|^(导出成片|生成成片|开始成片|直接成片|一键成片|成片导出)$|^(导出|生成|开始).{0,6}成片/

const JIANYING_RE = /导出剪映草稿|剪映草稿|^导出剪映/

const TTS_RE = /不保留原声|tts\s*配音|重新配音|配音导出/i

export function isExportLikeMessage(text: string): boolean {
  const t = text.trim()
  if (!t || t.length > 80) return false
  return REALIZE_RE.test(t) || JIANYING_RE.test(t) || TTS_RE.test(t)
}

export function idleReasonMessage(data: Record<string, unknown>): string | null {
  const reason = String(data.idle_reason || '')
  const detail = String(data.detail || '').trim()
  if (detail) return detail
  switch (reason) {
    case 'missing_prerequisite':
      return '缺少前置条件（例如尚未生成方案），请先完成上一步。'
    case 'model_text_only':
      return '助手只回复了文字，未执行成片。请再说「导出成片」，或使用中间方案区的「一键成片」。'
    case 'no_tool_for_export_intent':
      return '导出指令未被识别为工具调用，请重试或检查 LLM 配置。'
    case 'llm_error':
      return '模型 API 调用失败，请在「设置」中检查 LLM 地址与密钥。'
    case 'executor_error':
      return '对话执行异常，请查看后端日志或稍后重试。'
    case 'unknown_tool':
      return '内部工具未注册，请更新后端版本。'
    default:
      return reason ? `未执行操作（${reason}）` : null
  }
}
