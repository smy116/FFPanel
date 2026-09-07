import axios from 'axios'
import type { ApiError, BrowseEntry, CompanionFile, LogEntry, ScanSummary, Snapshot, StorageLocation, Task, TaskFile } from './types'

export const http = axios.create({ baseURL: '/api/v1', timeout: 30_000 })

async function loadAll<T>(path: string, limit: number): Promise<T[]> {
  const items: T[] = []
  let total = Infinity
  while (items.length < total) {
    const { data } = await http.get<{ items: T[]; total: number }>(path, { params: { offset: items.length, limit } })
    if (!data.items.length && items.length < data.total) throw new Error('文件列表加载不完整，请重试')
    items.push(...data.items)
    total = data.total
  }
  return items
}

http.interceptors.response.use(undefined, (error) => {
  const payload = error.response?.data as ApiError | { detail?: ApiError } | undefined
  const detail: ApiError | undefined = payload && 'detail' in payload ? payload.detail : payload as ApiError | undefined
  const normalized = new Error(detail?.message || error.message || '请求失败') as Error & { code?: string }
  normalized.code = detail?.code
  return Promise.reject(normalized)
})

export const api = {
  snapshot: () => http.get<Snapshot>('/snapshot').then(({ data }) => data),
  remotes: () => http.get<{ items: string[]; available: boolean }>('/remotes').then(({ data }) => data),
  browse: (location: StorageLocation) => http.post<{ items: BrowseEntry[] }>('/storage/browse', { location }).then(({ data }) => data.items),
  scan: (source: StorageLocation, companionFilePolicy: string) => http.post<ScanSummary>('/storage/scan', { source, companionFilePolicy }).then(({ data }) => data),
  createTask: (payload: Record<string, unknown>) => http.post<Task>('/tasks', payload).then(({ data }) => data),
  files: (taskId: string, limit = 500) => loadAll<TaskFile>(`/tasks/${taskId}/files`, limit),
  companions: (taskId: string, limit = 500) => loadAll<CompanionFile>(`/tasks/${taskId}/companions`, limit),
  logs: (taskId: string) => http.get<{ items: LogEntry[] }>(`/tasks/${taskId}/logs`).then(({ data }) => data.items),
  stop: (taskId: string) => http.post<Task>(`/tasks/${taskId}/stop`).then(({ data }) => data),
  retry: (taskId: string) => http.post<Task>(`/tasks/${taskId}/retry`).then(({ data }) => data),
  remove: (taskId: string) => http.delete(`/tasks/${taskId}`),
}
