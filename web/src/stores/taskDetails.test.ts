import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api'
import type { CompanionFile, EventEnvelope, LogEntry, Task, TaskFile, TranscodeProgress } from '../types'
import { useTasksStore } from './tasks'

vi.mock('../api', () => ({ api: { files: vi.fn(), companions: vi.fn(), logs: vi.fn(), retry: vi.fn(), snapshot: vi.fn() } }))

const file = (version = 1, stage: TaskFile['stage'] = 'pending'): TaskFile => ({
  id: 'file-1', taskId: 'task-1', relativePath: 'movie.mkv', stage, attempt: 1,
  sourceSize: 1, finalOutputPath: null, artifactSize: null, progress: null, ffmpegOutput: null,
  lastError: null, lastExitCode: null, version, startedAt: null, finishedAt: null, updatedAt: '',
})
const event = (type: string, payload: unknown, version = 0): EventEnvelope => ({
  id: String(version), type, taskId: 'task-1', fileId: 'file-1', version, updatedAt: '', payload,
})
const log: LogEntry = { level: 'info', message: 'finished', fileId: 'file-1', createdAt: '2026-09-07T00:00:00Z' }

describe('live task details', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    setActivePinia(createPinia())
    vi.mocked(api.files).mockResolvedValue([file()])
    vi.mocked(api.companions).mockResolvedValue([])
    vi.mocked(api.logs).mockResolvedValue([])
  })

  it('updates file states, companion states and logs without reopening', async () => {
    const store = useTasksStore()
    await store.loadDetails('task-1')
    store.mergeEvent(event('file.state', file(2, 'completed'), 2))
    const companion: CompanionFile = { id: 'sub-1', taskId: 'task-1', relativePath: 'movie.srt', category: 'subtitle', stage: 'completed', attempt: 1, sourceSize: 1, finalOutputPath: null, lastError: null, version: 2, updatedAt: '' }
    store.mergeEvent({ ...event('companion.state', companion, 2), fileId: companion.id })
    store.mergeEvent(event('log.append', log))
    expect(store.details['task-1'].files[0].stage).toBe('completed')
    expect(store.details['task-1'].companions[0].stage).toBe('completed')
    expect(store.details['task-1'].logs).toEqual([log])
    store.mergeEvent(event('file.state', file(1), 1))
    expect(store.details['task-1'].files[0].stage).toBe('completed')
  })

  it('keeps events received while the initial detail request is pending', async () => {
    let resolve!: (files: TaskFile[]) => void
    vi.mocked(api.files).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    vi.mocked(api.logs).mockResolvedValueOnce([log])
    const store = useTasksStore()
    const loading = store.loadDetails('task-1')
    store.mergeEvent(event('file.state', file(2, 'completed'), 2))
    store.mergeEvent(event('log.append', log))
    resolve([file()])
    await loading
    expect(store.details['task-1'].files[0].stage).toBe('completed')
    expect(store.details['task-1'].logs).toEqual([log])
  })

  it('ignores older concurrent detail responses', async () => {
    let resolve!: (files: TaskFile[]) => void
    vi.mocked(api.files).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const store = useTasksStore()
    const first = store.loadDetails('task-1')
    vi.mocked(api.files).mockResolvedValueOnce([file(3, 'completed')])
    await store.loadDetails('task-1')
    resolve([file()])
    await first
    expect(store.details['task-1'].files[0].version).toBe(3)
  })

  it('reloads cached details after Retry', async () => {
    const store = useTasksStore()
    await store.loadDetails('task-1')
    vi.mocked(api.retry).mockResolvedValue({ id: 'task-1', status: 'queued', version: 3 } as Task)
    vi.mocked(api.files).mockResolvedValueOnce([file(3)])
    await store.retry('task-1')
    expect(api.files).toHaveBeenCalledTimes(2)
    expect(store.details['task-1'].files[0].version).toBe(3)
  })

  it('refreshes details when another client retries the task', async () => {
    const store = useTasksStore()
    store.tasks = [{ id: 'task-1', retryCount: 0, status: 'stopped', version: 2, completedFiles: 0 } as Task]
    await store.loadDetails('task-1')
    vi.mocked(api.files).mockResolvedValueOnce([file(3)])
    store.mergeEvent(event('task.state', { ...store.tasks[0], retryCount: 1, status: 'queued', version: 3 }, 3))
    await vi.waitFor(() => expect(store.details['task-1'].files[0].version).toBe(3))
    expect(api.files).toHaveBeenCalledTimes(2)
  })

  it('caps live logs at 300 entries', async () => {
    const store = useTasksStore()
    await store.loadDetails('task-1')
    for (let index = 0; index < 305; index++) store.mergeEvent(event('log.append', { ...log, message: String(index) }))
    expect(store.details['task-1'].logs).toHaveLength(300)
    expect(store.details['task-1'].logs[0].message).toBe('5')
  })

  it('updates transcode progress but does not apply late progress to completed files', async () => {
    vi.mocked(api.files).mockResolvedValueOnce([file(2, 'transcoding')])
    const store = useTasksStore()
    await store.loadDetails('task-1')
    const progress = { percent: 50, updatedAt: '2026-09-07T00:00:00Z' } as TranscodeProgress
    store.mergeEvent(event('transcode.progress', progress, 3))
    expect(store.details['task-1'].files[0].progress?.percent).toBe(50)
    store.mergeEvent(event('file.state', file(4, 'completed'), 4))
    store.mergeEvent(event('transcode.progress', { ...progress, percent: 60 }))
    expect(store.details['task-1'].files[0].progress).toBeNull()
  })

  it('reloads cached details when SSE reconnects', async () => {
    class FakeEventSource {
      onopen: (() => void) | null = null
      addEventListener() {}
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    try {
      const store = useTasksStore()
      vi.mocked(api.snapshot).mockResolvedValue({ tasks: [], system: store.system, metrics: store.metrics })
      await store.loadDetails('task-1')
      store.connectEvents()
      vi.mocked(api.files).mockResolvedValueOnce([file(5, 'completed')])
      const source = store.eventSource as unknown as FakeEventSource
      source.onopen?.()
      await vi.waitFor(() => expect(store.details['task-1'].files[0].version).toBe(5))
      expect(api.files).toHaveBeenCalledTimes(2)
    } finally { vi.unstubAllGlobals() }
  })

  it('exposes detail load errors so the user can retry', async () => {
    vi.mocked(api.files).mockRejectedValueOnce(new Error('connection lost'))
    const store = useTasksStore()
    await store.loadDetails('task-1')
    expect(store.details['task-1'].loading).toBe(false)
    expect(store.details['task-1'].error).toBe('connection lost')
    await store.loadDetails('task-1')
    expect(store.details['task-1'].error).toBe('')
  })
})
