'use client'

import { useCallback, useEffect, useState } from 'react'
import clsx from 'clsx'
import {
  CheckCircle2,
  Loader2,
  Plug,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Wrench,
  XCircle,
} from 'lucide-react'
import { agentMcpApi, type McpServerConfig, type McpTestResult } from '@/lib/agent-api'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'

/**
 * MCP 服务管理：外部工具服务器（stdio 本地命令 / http 远程）接入工作台 Agent。
 * 工具以 mcp__<server>__<tool> 桥接，默认执行前确认；trusted 服务在「自动审核」档免确认。
 */
export function AgentMcpSection() {
  const toast = useToast()
  const confirm = useConfirm()
  const [servers, setServers] = useState<McpServerConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [testing, setTesting] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, McpTestResult>>({})
  const [showCreate, setShowCreate] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    agentMcpApi
      .list()
      .then(setServers)
      .catch(() => setError('MCP 服务列表加载失败，请确认后端服务正常'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const runTest = async (server: McpServerConfig) => {
    setTesting(server.id)
    try {
      const result = await agentMcpApi.test(server)
      setTestResults((prev) => ({ ...prev, [server.id]: result }))
      if (result.ok) toast.success(`连接成功，发现 ${result.tool_count} 个工具`)
      else toast.error(`连接失败：${result.error}`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setTesting(null)
    }
  }

  const toggleEnabled = async (server: McpServerConfig) => {
    try {
      const res = await agentMcpApi.patch(server.id, { enabled: !server.enabled })
      setServers((prev) => prev.map((s) => (s.id === server.id ? res.server : s)))
      toast.success(`「${server.name}」已${server.enabled ? '停用' : '启用'}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const toggleTrusted = async (server: McpServerConfig) => {
    const next = !server.trusted
    if (next) {
      const ok = await confirm({
        title: '信任该 MCP 服务？',
        description:
          `信任后「${server.name}」的工具在自动审核档位下将跳过执行确认直接运行。` +
          '仅在你了解该服务提供方且工具无破坏性副作用时开启。',
        confirmLabel: '信任',
        variant: 'danger',
      })
      if (!ok) return
    }
    try {
      const res = await agentMcpApi.patch(server.id, { trusted: next })
      setServers((prev) => prev.map((s) => (s.id === server.id ? res.server : s)))
      toast.success(next ? `已信任「${server.name}」` : `已取消信任「${server.name}」`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const handleDelete = async (server: McpServerConfig) => {
    const ok = await confirm({
      title: '删除该 MCP 服务？',
      description: `「${server.name}」的配置将被删除，其工具不再对 Agent 可用。`,
      confirmLabel: '删除',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await agentMcpApi.remove(server.id)
      toast.success('已删除')
      load()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const enabledCount = servers.filter((s) => s.enabled).length

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100 flex items-center gap-1.5">
            <Plug className="w-4 h-4 text-cyan-400" />
            MCP 外部工具
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            接入 MCP 服务器扩展 Agent 能力（文件/浏览器/任意工具）；工具默认执行前确认
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500">启用 {enabledCount}/{servers.length}</span>
          <button
            type="button"
            onClick={load}
            title="刷新"
            className="p-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
          >
            <RefreshCw size={13} className={clsx(loading && 'animate-spin')} />
          </button>
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            添加服务
          </button>
        </div>
      </div>

      <div className="px-6 py-5 space-y-3">
        {error && <p className="text-sm text-rose-300">{error}</p>}
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-4">
            <Loader2 className="w-4 h-4 animate-spin" />加载 MCP 服务…
          </div>
        ) : servers.length === 0 && !showCreate ? (
          <div className="py-6 text-center">
            <p className="text-sm text-slate-500">尚未配置 MCP 服务</p>
            <p className="mt-1 text-[11px] text-slate-600">
              例：npx -y @modelcontextprotocol/server-filesystem F:\\素材（本地文件工具）
            </p>
          </div>
        ) : (
          servers.map((server) => {
            const t = testResults[server.id]
            return (
              <div
                key={server.id}
                className={clsx(
                  'rounded-xl border transition-colors',
                  server.enabled
                    ? 'border-cyan-500/25 bg-cyan-500/[0.04]'
                    : 'border-slate-800 bg-slate-900/40 opacity-70',
                )}
              >
                <div className="flex flex-wrap items-start gap-3 p-3.5">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-medium text-slate-100">{server.name}</span>
                      <span className="rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400 font-mono">
                        {server.id}
                      </span>
                      <span className="rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400">
                        {server.transport === 'stdio' ? '本地 stdio' : '远程 HTTP'}
                      </span>
                      {server.trusted && (
                        <span
                          title="自动审核档位下免确认"
                          className="inline-flex items-center gap-0.5 rounded border border-emerald-500/40 bg-emerald-500/10 px-1 py-px text-[10px] text-emerald-300"
                        >
                          <ShieldCheck size={9} /> 已信任
                        </span>
                      )}
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-slate-500 truncate">
                      {server.transport === 'stdio'
                        ? [server.command, ...server.args].join(' ')
                        : server.url}
                    </p>
                    {t && (
                      <div
                        className={clsx(
                          'mt-2 rounded-lg border px-2.5 py-1.5 text-[11px]',
                          t.ok
                            ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200'
                            : 'border-rose-500/30 bg-rose-500/5 text-rose-200',
                        )}
                      >
                        {t.ok ? (
                          <>
                            <span className="inline-flex items-center gap-1 font-medium">
                              <CheckCircle2 size={11} /> 连接成功 · {t.tool_count} 个工具
                            </span>
                            <span className="mt-1 flex flex-wrap gap-1">
                              {(t.tools || []).slice(0, 8).map((tool) => (
                                <span
                                  key={tool.name}
                                  title={tool.description}
                                  className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1 py-px font-mono text-[10px]"
                                >
                                  {tool.name}
                                </span>
                              ))}
                            </span>
                          </>
                        ) : (
                          <span className="inline-flex items-center gap-1">
                            <XCircle size={11} /> {t.error}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => void runTest(server)}
                      disabled={testing === server.id}
                      className="flex items-center gap-1 rounded-lg border border-cyan-500/50 bg-cyan-500/10 px-2.5 py-1.5 text-xs text-cyan-200 transition-colors hover:bg-cyan-500/20 disabled:opacity-50"
                    >
                      {testing === server.id ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Wrench size={11} />
                      )}
                      测试连接
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggleTrusted(server)}
                      title={server.trusted ? '取消信任' : '信任（自动审核档免确认）'}
                      className={clsx(
                        'rounded-lg border px-2 py-1.5 text-xs transition-colors',
                        server.trusted
                          ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20'
                          : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500',
                      )}
                    >
                      <ShieldCheck size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggleEnabled(server)}
                      title={server.enabled ? '停用' : '启用'}
                      className={clsx(
                        'relative h-5 w-9 rounded-full transition-colors',
                        server.enabled ? 'bg-emerald-500/70' : 'bg-slate-700',
                      )}
                    >
                      <span
                        className={clsx(
                          'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all',
                          server.enabled ? 'left-[18px]' : 'left-0.5',
                        )}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDelete(server)}
                      title="删除"
                      className="p-1.5 rounded-lg text-slate-500 hover:text-rose-300 hover:bg-rose-500/10 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              </div>
            )
          })
        )}

        {showCreate && (
          <McpServerForm
            onDone={() => {
              setShowCreate(false)
              load()
            }}
            onCancel={() => setShowCreate(false)}
          />
        )}
      </div>
    </section>
  )
}

/** 解析粘贴的 MCP JSON：单条配置 / 配置数组 / Claude·Cursor 的 {mcpServers:{…}} 格式。 */
function parseMcpJson(text: string): Partial<McpServerConfig> & { env?: Record<string, string> } {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error('不是合法 JSON')
  }
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const obj = data as Record<string, unknown>
    // Claude Desktop / Cursor 格式：{ "mcpServers": { "<id>": { command… | url… } } }
    if (obj.mcpServers && typeof obj.mcpServers === 'object') {
      const map = obj.mcpServers as Record<string, Record<string, unknown>>
      const firstKey = Object.keys(map)[0]
      if (!firstKey) throw new Error('mcpServers 为空')
      const entry = map[firstKey]
      return {
        id: firstKey,
        name: String(entry.name || firstKey),
        transport: entry.url ? 'http' : 'stdio',
        command: String(entry.command || ''),
        args: Array.isArray(entry.args) ? entry.args.map(String) : [],
        env: (entry.env as Record<string, string>) || undefined,
        url: String(entry.url || ''),
        headers: (entry.headers as Record<string, string>) || undefined,
      }
    }
    if (Array.isArray(obj)) throw new Error('意外的数组')
    return {
      id: obj.id ? String(obj.id) : undefined,
      name: obj.name ? String(obj.name) : undefined,
      transport: obj.url ? 'http' : 'stdio',
      command: String(obj.command || ''),
      args: Array.isArray(obj.args) ? obj.args.map(String) : [],
      env: (obj.env as Record<string, string>) || undefined,
      url: String(obj.url || ''),
      headers: (obj.headers as Record<string, string>) || undefined,
    }
  }
  throw new Error('需要对象或 {mcpServers:{…}} 格式')
}

function McpServerForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const toast = useToast()
  const [transport, setTransport] = useState<'stdio' | 'http'>('stdio')
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [argsText, setArgsText] = useState('')
  const [url, setUrl] = useState('')
  const [env, setEnv] = useState<Record<string, string>>({})
  const [headers, setHeaders] = useState<Record<string, string>>({})
  const [showJson, setShowJson] = useState(false)
  const [jsonText, setJsonText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const inputCls =
    'w-full rounded-lg border border-slate-700 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500/60 focus:outline-none'

  const buildConfig = () => ({
    id: id.trim().toLowerCase() || undefined,
    name: name.trim() || id.trim(),
    transport,
    command: command.trim(),
    args: argsText.trim() ? argsText.trim().split(/\s+/) : [],
    env,
    url: url.trim(),
    headers,
    enabled: true,
    trusted: false,
  })

  const applyJson = () => {
    try {
      const parsed = parseMcpJson(jsonText)
      if (parsed.transport) setTransport(parsed.transport)
      if (parsed.id) setId(parsed.id)
      if (parsed.name) setName(parsed.name)
      if (parsed.command) setCommand(parsed.command)
      if (parsed.args?.length) setArgsText(parsed.args.join(' '))
      if (parsed.url) setUrl(parsed.url)
      if (parsed.env && Object.keys(parsed.env).length) setEnv(parsed.env)
      if (parsed.headers && Object.keys(parsed.headers).length) setHeaders(parsed.headers)
      toast.success('已解析 JSON 并填入表单，请检查后「先测试」再添加')
      setShowJson(false)
    } catch (e) {
      toast.error(`JSON 解析失败：${(e as Error).message}`)
    }
  }

  const submit = async () => {
    setSubmitting(true)
    try {
      await agentMcpApi.upsert(buildConfig())
      toast.success('MCP 服务已添加，可点「测试连接」验证')
      onDone()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const submitTest = async () => {
    setSubmitting(true)
    try {
      const result = await agentMcpApi.test(buildConfig())
      if (result.ok) {
        toast.success(`连接成功：${result.tool_count} 个工具（未保存，确认无误后点添加）`)
      } else {
        toast.error(`连接失败：${result.error}`)
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/[0.04] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-100">添加 MCP 服务</p>
        <button
          type="button"
          onClick={() => setShowJson((v) => !v)}
          className="text-[11px] text-cyan-300 hover:text-cyan-200 transition-colors"
        >
          {showJson ? '收起 JSON 导入' : '从 JSON 导入'}
        </button>
      </div>
      {showJson && (
        <div className="space-y-1.5">
          <textarea
            className={clsx(inputCls, 'min-h-[90px] resize-y font-mono text-xs')}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            placeholder={
              '{\n  "mcpServers": {\n    "fetch": { "command": "uvx", "args": ["mcp-server-fetch"] }\n  }\n}'
            }
          />
          <button
            type="button"
            onClick={applyJson}
            className="px-3 py-1.5 rounded-lg border border-cyan-500/50 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20 text-xs transition-colors"
          >
            解析并填入
          </button>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs text-slate-400">标识 id（小写，3~32 位）</label>
          <input
            className={inputCls}
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="如 fs、browser"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-400">显示名称</label>
          <input
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如 本地文件工具"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-400">传输方式</label>
          <div className="flex gap-1.5 pt-1">
            {(['stdio', 'http'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTransport(t)}
                className={clsx(
                  'flex-1 rounded-lg border px-2 py-1.5 text-xs transition-colors',
                  transport === t
                    ? 'border-indigo-500/60 bg-indigo-500/15 text-indigo-200'
                    : 'border-slate-700 text-slate-400 hover:text-slate-200',
                )}
              >
                {t === 'stdio' ? '本地 stdio' : '远程 HTTP'}
              </button>
            ))}
          </div>
        </div>
      </div>
      {transport === 'stdio' ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label className="text-xs text-slate-400">命令 *</label>
            <input
              className={inputCls}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="如 npx / uvx / python"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-slate-400">参数（空格分隔）</label>
            <input
              className={inputCls}
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              placeholder="-y @modelcontextprotocol/server-filesystem F:\素材"
            />
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <label className="text-xs text-slate-400">服务地址（Streamable HTTP）*</label>
          <input
            className={inputCls}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://127.0.0.1:9000/mcp"
          />
        </div>
      )}
      {(Object.keys(env).length > 0 || Object.keys(headers).length > 0) && (
        <p className="text-[11px] text-slate-500">
          已携带 {Object.keys(env).length} 个环境变量、{Object.keys(headers).length} 个鉴权头（来自 JSON 导入，随配置保存）
        </p>
      )}
      <p className="text-[11px] leading-4 text-slate-500">
        工具将以 mcp__&lt;id&gt;__&lt;工具名&gt; 提供给 Agent，默认执行前需确认（权限「每次询问」档）；
        也可在工作台对话中直接让 Agent 代为接入（安装前同样会弹确认卡）。
      </p>
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:text-slate-100 text-xs transition-colors"
        >
          取消
        </button>
        <button
          type="button"
          onClick={() => void submitTest()}
          disabled={submitting}
          className="px-3 py-1.5 rounded-lg border border-cyan-500/50 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20 text-xs disabled:opacity-50 transition-colors"
        >
          先测试
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={submitting}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium disabled:opacity-50 transition-colors"
        >
          {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          添加
        </button>
      </div>
    </div>
  )
}
