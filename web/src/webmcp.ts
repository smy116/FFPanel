import { api } from './api'

declare global {
  interface Document {
    modelContext?: {
      registerTool(tool: Record<string, unknown>, options?: { signal?: AbortSignal }): void | Promise<void>
    }
  }
}

export function registerTaskTool(): () => void {
  const context = document.modelContext
  if (!context?.registerTool) return () => undefined
  const lifecycle = new AbortController()
  void Promise.resolve(context.registerTool({
    name: 'create_transcode_task',
    title: '创建 FFPanel 转码任务',
    description: '扫描一个已挂载的本地媒体目录，并用受控参数创建批量转码任务。',
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        sourcePath: { type: 'string' }, destinationPath: { type: 'string' },
        name: { type: 'string' }, videoCodec: { enum: ['h264', 'hevc'] },
        container: { enum: ['mp4', 'mkv'] }, height: { enum: [-1, 360, 480, 720, 1080, 2160] },
        bitrateKbps: { type: 'integer', minimum: 100, maximum: 100000 },
      },
      required: ['sourcePath', 'destinationPath'],
    },
    annotations: { readOnlyHint: false, untrustedContentHint: false },
    async execute(raw: unknown) {
      const input = raw as Record<string, unknown>
      if (typeof input.sourcePath !== 'string' || typeof input.destinationPath !== 'string') throw new Error('sourcePath 和 destinationPath 必须是字符串')
      const source = { kind: 'local' as const, path: input.sourcePath }
      const summary = await api.scan(source, 'subtitles')
      const task = await api.createTask({
        name: typeof input.name === 'string' ? input.name : undefined,
        source, destination: { kind: 'local', path: input.destinationPath }, scanToken: summary.scanToken,
        companionFilePolicy: 'subtitles', params: {
          hardwareMode: 'cpu_cpu', autoFallback: true, videoCodec: input.videoCodec || 'h264', container: input.container || 'mp4',
          height: input.height ?? 720, bitrateKbps: input.bitrateKbps ?? 2000, smartBitrateCap: true,
          frameRate: 'source', rateControl: 'vbr', audioStrategy: 'copy', subtitleStrategy: 'auto',
        },
      })
      return { id: task.id, status: task.status, videoCount: task.totalFiles }
    },
  }, { signal: lifecycle.signal })).catch(() => undefined)
  return () => lifecycle.abort()
}

