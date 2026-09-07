import { defineStore } from 'pinia'
import { api } from '../api'
import { mergeDetailEvent, type TaskDetails } from './taskDetails'
import type { EventEnvelope, Metrics, SystemStatus, Task, TaskFile, TranscodeProgress } from '../types'

const EMPTY_SYSTEM: SystemStatus = {
  ffmpegVersion: null, ffprobeAvailable: false, rcloneAvailable: false,
  mppAvailable: false, rgaAvailable: false, encoders: [], decoders: [], filters: [], devices: {},
  error: null, transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0,
}
const EMPTY_METRICS: Metrics = { queuedTasks: 0, completedTasks: 0, completedVideos: 0, sourceBytes: 0, outputBytes: 0 }

export const useTasksStore = defineStore('tasks', {
  state: () => ({
    tasks: [] as Task[], system: { ...EMPTY_SYSTEM }, metrics: { ...EMPTY_METRICS },
    remotes: [] as string[], loading: false, connected: false, error: '',
    eventSource: null as EventSource | null, retryTimer: 0, retryAttempt: 0,
    versions: {} as Record<string, number>,
    details: {} as Record<string, TaskDetails>,
    detailRequests: {} as Record<string, number>,
    detailEvents: {} as Record<string, EventEnvelope[]>,
  }),
  getters: {
    pendingCount: (state) => state.tasks.filter((task) => ['queued', 'running'].includes(task.status)).length,
    interruptedCount: (state) => state.tasks.filter((task) => task.status === 'interrupted').length,
  },
  actions: {
    async loadDetails(taskId: string) {
      const requestId = (this.detailRequests[taskId] || 0) + 1
      this.detailRequests[taskId] = requestId
      this.detailEvents[taskId] = []
      this.details[taskId] ??= { files: [], companions: [], logs: [], loading: false, error: '' }
      this.details[taskId].loading = true
      this.details[taskId].error = ''
      try {
        const [files, companions, logs] = await Promise.all([api.files(taskId), api.companions(taskId), api.logs(taskId)])
        if (this.detailRequests[taskId] !== requestId) return
        const details: TaskDetails = { files, companions, logs, loading: false, error: '' }
        for (const event of this.detailEvents[taskId] || []) mergeDetailEvent(details, event)
        this.details[taskId] = details
      } catch (error) {
        if (this.detailRequests[taskId] === requestId) {
          this.details[taskId].error = error instanceof Error ? error.message : '详情加载失败'
        }
      } finally {
        if (this.detailRequests[taskId] === requestId) {
          this.details[taskId].loading = false
          delete this.detailEvents[taskId]
        }
      }
    },
    async loadSnapshot() {
      this.loading = true
      try {
        const data = await api.snapshot()
        this.tasks = data.tasks
        this.system = data.system
        this.metrics = data.metrics
        this.error = ''
      } catch (error) {
        this.error = error instanceof Error ? error.message : '无法读取任务状态'
      } finally { this.loading = false }
    },
    async loadRemotes() {
      try { this.remotes = (await api.remotes()).items } catch { this.remotes = [] }
    },
    connectEvents() {
      if (this.eventSource) return
      const source = new EventSource('/api/v1/events', { withCredentials: true })
      this.eventSource = source
      source.onopen = () => {
        this.connected = true
        this.retryAttempt = 0
        void this.loadSnapshot()
        for (const taskId of Object.keys(this.details)) void this.loadDetails(taskId)
      }
      const names = ['task.state', 'file.state', 'companion.state', 'transcode.progress', 'task.metrics', 'system.status', 'log.append']
      for (const name of names) source.addEventListener(name, (raw) => this.mergeEvent(JSON.parse((raw as MessageEvent).data)))
      source.onerror = () => {
        this.connected = false
        source.close()
        this.eventSource = null
        const delays = [1000, 2000, 5000, 10_000]
        const delay = delays[Math.min(this.retryAttempt, delays.length - 1)]
        this.retryAttempt += 1
        window.clearTimeout(this.retryTimer)
        this.retryTimer = window.setTimeout(() => this.connectEvents(), delay)
      }
    },
    mergeEvent(event: EventEnvelope) {
      if (event.type === 'system.status') {
        this.system = { ...this.system, ...(event.payload as SystemStatus) }
        return
      }
      if (!event.taskId) return
      const key = `${event.type}:${event.taskId}:${event.fileId || ''}`
      if (event.version && (this.versions[key] || 0) >= event.version) return
      if (event.version) this.versions[key] = event.version
      const details = this.details[event.taskId]
      if (details && ['file.state', 'companion.state', 'transcode.progress', 'log.append'].includes(event.type)) {
        this.detailEvents[event.taskId]?.push(event)
        mergeDetailEvent(details, event)
      }
      const index = this.tasks.findIndex((task) => task.id === event.taskId)
      if (event.type === 'task.state' || event.type === 'task.metrics') {
        const incoming = event.payload as Task
        const previousStatus = index >= 0 ? this.tasks[index]?.status : undefined
        const previousRetryCount = index >= 0 ? this.tasks[index]?.retryCount : undefined
        if (index < 0) this.tasks.unshift(incoming)
        else if ((this.tasks[index]?.version || 0) <= incoming.version) this.tasks[index] = { ...this.tasks[index], ...incoming }
        this.sortTasks()
        this.metrics.queuedTasks = this.tasks.filter((task) => task.status === 'queued').length
        this.metrics.completedTasks = this.tasks.filter((task) => task.status === 'completed').length
        this.metrics.completedVideos = this.tasks.reduce((total, task) => total + task.completedFiles, 0)
        if (event.type === 'task.state' && details && previousRetryCount !== undefined && incoming.retryCount > previousRetryCount) {
          void this.loadDetails(event.taskId)
        }
        const terminal = ['completed', 'failed', 'partial_failed', 'stopped', 'interrupted']
        if (event.type === 'task.state' && previousStatus !== incoming.status && terminal.includes(incoming.status)) {
          void this.loadSnapshot()
        }
      } else if (index >= 0 && event.type === 'transcode.progress') {
        const task = this.tasks[index]
        if (task?.activeTranscodeFile?.id === event.fileId) task.activeTranscodeFile.progress = event.payload as TranscodeProgress
      } else if (index >= 0 && event.type === 'file.state') {
        const item = event.payload as TaskFile
        const task = this.tasks[index]
        if (task?.currentTranscodeFileId === item.id) task.activeTranscodeFile = item
        if (task?.currentUploadFileId === item.id) task.activeUploadFile = item
      }
    },
    sortTasks() {
      const order: Record<string, number> = { running: 0, queued: 1, interrupted: 2, partial_failed: 2, failed: 2, completed: 3, stopped: 3 }
      this.tasks.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || Date.parse(b.createdAt) - Date.parse(a.createdAt))
    },
    async stop(taskId: string) { this.replaceTask(await api.stop(taskId)) },
    async retry(taskId: string) {
      this.replaceTask(await api.retry(taskId))
      if (this.details[taskId]) await this.loadDetails(taskId)
    },
    async remove(taskId: string) {
      await api.remove(taskId)
      this.tasks = this.tasks.filter((task) => task.id !== taskId)
      delete this.details[taskId]
      delete this.detailRequests[taskId]
      delete this.detailEvents[taskId]
    },
    replaceTask(task: Task) {
      const index = this.tasks.findIndex((item) => item.id === task.id)
      if (index < 0) this.tasks.unshift(task); else this.tasks[index] = { ...this.tasks[index], ...task }
      this.sortTasks()
    },
  },
})
