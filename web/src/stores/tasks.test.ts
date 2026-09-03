import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTasksStore } from './tasks'
import type { EventEnvelope, Task } from '../types'

const task = (version: number, status: Task['status'] = 'queued'): Task => ({
  id: 'task-1', name: 'Demo', status,
  source: { kind: 'local', path: '/media/in' }, destination: { kind: 'local', path: '/media/out' },
  requestedParams: { hardwareMode: 'cpu_cpu', autoFallback: true, videoCodec: 'h264', container: 'mp4', height: 720, bitrateKbps: 2000, smartBitrateCap: true, frameRate: 'source', gop: 120, audioStrategy: 'copy', subtitleStrategy: 'auto' },
  companionFilePolicy: 'subtitles', totalFiles: 1, completedFiles: status === 'completed' ? 1 : 0,
  failedFiles: 0, skippedFiles: 0, companionTotal: 0, companionCompleted: 0, companionFailed: 0,
  percent: status === 'completed' ? 100 : 0, currentTranscodeFileId: null, currentUploadFileId: null,
  retryCount: 0, lastError: null, interruptedReason: null, version,
  createdAt: '2026-01-01T00:00:00Z', startedAt: null, finishedAt: null, updatedAt: '2026-01-01T00:00:00Z',
})

describe('task SSE merge', () => {
  beforeEach(() => setActivePinia(createPinia()))

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
})

