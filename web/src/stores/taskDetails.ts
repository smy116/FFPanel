import type { CompanionFile, EventEnvelope, LogEntry, TaskFile, TranscodeProgress } from '../types'

export interface TaskDetails {
  files: TaskFile[]
  companions: CompanionFile[]
  logs: LogEntry[]
  loading: boolean
  error: string
}

function mergeFile<T extends { id: string; version: number }>(items: T[], incoming: T) {
  const index = items.findIndex((item) => item.id === incoming.id)
  if (index < 0) items.push(incoming)
  else if (items[index].version <= incoming.version) items[index] = { ...items[index], ...incoming }
}

export function mergeDetailEvent(details: TaskDetails, event: EventEnvelope) {
  if (event.type === 'file.state') mergeFile(details.files, event.payload as TaskFile)
  else if (event.type === 'companion.state') mergeFile(details.companions, event.payload as CompanionFile)
  else if (event.type === 'transcode.progress') {
    const file = details.files.find((item) => item.id === event.fileId)
    const progress = event.payload as TranscodeProgress
    if (file?.stage === 'transcoding' && (!event.version || event.version >= file.version)
      && (!file.progress || progress.updatedAt >= file.progress.updatedAt)) {
      file.progress = progress
      file.version = Math.max(file.version, event.version)
    }
  } else if (event.type === 'log.append') {
    const log = event.payload as LogEntry
    if (!details.logs.some((item) => item.createdAt === log.createdAt && item.fileId === log.fileId
      && item.level === log.level && item.message === log.message)) details.logs.push(log)
    details.logs = details.logs.slice(-300)
  }
}
