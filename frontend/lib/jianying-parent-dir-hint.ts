/** 未配置剪映草稿父目录时导出为 ZIP，提示用户可在设置中启用「直写目录」以更方便使用。 */

export type ToastInfoFn = (message: string, duration?: number) => void

export function toastRecommendJianyingParentDir(toast: { info: ToastInfoFn }) {
  toast.info(
    '提示：在「设置 → 视频处理 → 剪映草稿导出」中配置「剪映草稿父目录」后，可跳过 ZIP、直接写入剪映目录，使用更方便。',
    7000,
  )
}
