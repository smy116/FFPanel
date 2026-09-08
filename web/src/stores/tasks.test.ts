import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api'
import { useTasksStore } from './tasks'
import type { EventEnvelope, Snapshot, Task } from '../types'

vi.mock('../api', () => ({ api: { snapshot: vi.fn() } }))

const task = (version: number, status: Task['status'] = 'queued'): Task => ({
  id: 'task-1', name: 'Demo', status,
  source: { kind: 'local', path: '/media/in' }, destination: { kind: 'local', path: '/media/out' },
  requestedParams: { hardwareMode: 'cpu_cpu', autoFallback: true, videoCodec: 'h264', container: 'mp4', height: 720, bitrateKbps: 2000, smartBitrateCap: true, frameRate: 'source', rateControl: 'vbr', audioStrategy: 'copy', subtitleStrategy: 'auto' },
  companionFilePolicy: 'subtitles', totalFiles: 1, completedFiles: status === 'completed' ? 1 : 0,
  failedFiles: 0, skippedFiles: 0, companionTotal: 0, companionCompleted: 0, companionFailed: 0,
  percent: status === 'completed' ? 100 : 0, currentTranscodeFileId: null, currentUploadFileId: null,
  retryCount: 0, lastError: null, interruptedReason: null, version,
  createdAt: '2026-01-01T00:00:00Z', startedAt: null, finishedAt: null, updatedAt: '2026-01-01T00:00:00Z',
})

const snapshot = (tasks: Task[]): Snapshot => ({
  tasks,
  system: {
    ffmpegVersion: 'test', ffprobeAvailable: true, rcloneAvailable: false,
    mppAvailable: false, rgaAvailable: false, encoders: [], decoders: [], filters: [], devices: {},
    error: null, transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0,
  },
  metrics: { queuedTasks: 0, completedTasks: 0, completedVideos: 0, sourceBytes: 0, outputBytes: 0 },
})

describe('task SSE merge', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    setActivePinia(createPinia())
  })

  it('rejects stale entity versions', () => {
    const store = useTasksStore()
    store.mergeEvent({ id: '2', type: 'task.state', version: 2, taskId: 'task-1', fileId: null, updatedAt: '', payload: task(2, 'running') } as EventEnvelope)
    store.mergeEvent({ id: '1', type: 'task.state', version: 1, taskId: 'task-1', fileId: null, updatedAt: '', payload: task(1, 'queued') } as EventEnvelope)
    expect(store.tasks[0]?.status).toBe('running')
    expect(store.tasks[0]?.version).toBe(2)
  })

  it('merges nullable structured progress without inventing values', () => {
    const store = useTasksStore()
    const value = task(2, 'running')
    value.currentTranscodeFileId = 'file-1'
    value.activeTranscodeFile = { id: 'file-1', taskId: 'task-1', relativePath: 'movie.mkv', stage: 'transcoding', attempt: 1, sourceSize: 1, finalOutputPath: null, artifactSize: null, progress: null, ffmpegOutput: null, lastError: null, lastExitCode: null, version: 1, startedAt: null, finishedAt: null, updatedAt: '' }
    store.tasks = [value]
    store.mergeEvent({ id: '3', type: 'transcode.progress', version: 3, taskId: 'task-1', fileId: 'file-1', updatedAt: '', payload: { taskId: 'task-1', fileId: 'file-1', stage: 'transcoding', frame: 99, fps: 30, bitrateKbps: null, outTimeMs: 1000, totalSizeBytes: null, speed: 1, percent: null, etaSeconds: null, progress: 'continue', updatedAt: '' } } as EventEnvelope)
    expect(store.tasks[0]?.activeTranscodeFile?.progress?.percent).toBeNull()
    expect(store.tasks[0]?.activeTranscodeFile?.progress?.etaSeconds).toBeNull()
  })

  it('does not let a delayed snapshot overwrite a newer SSE task', async () => {
    let resolve!: (value: Snapshot) => void
    vi.mocked(api.snapshot).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const store = useTasksStore()
    const loading = store.loadSnapshot()

    store.mergeEvent({
      id: '2', type: 'task.state', version: 2, taskId: 'task-1', fileId: null,
      updatedAt: '', payload: task(2, 'running'),
    } as EventEnvelope)
    resolve(snapshot([task(1, 'queued')]))
    await loading

    expect(store.tasks[0]?.status).toBe('running')
    expect(store.tasks[0]?.version).toBe(2)
    expect(store.metrics.queuedTasks).toBe(0)
  })

  it('ignores an older concurrent snapshot response', async () => {
    let resolveFirst!: (value: Snapshot) => void
    let resolveSecond!: (value: Snapshot) => void
    vi.mocked(api.snapshot)
      .mockReturnValueOnce(new Promise((done) => { resolveFirst = done }))
      .mockReturnValueOnce(new Promise((done) => { resolveSecond = done }))
    const store = useTasksStore()
    const first = store.loadSnapshot()
    const second = store.loadSnapshot()

    resolveSecond(snapshot([task(3, 'completed')]))
    await second
    resolveFirst(snapshot([task(1, 'queued')]))
    await first

    expect(store.tasks[0]?.status).toBe('completed')
    expect(store.tasks[0]?.version).toBe(3)
    expect(store.loading).toBe(false)
  })
})

