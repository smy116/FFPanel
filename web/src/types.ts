export type TaskStatus = 'queued' | 'running' | 'completed' | 'partial_failed' | 'failed' | 'stopped' | 'interrupted'
export type FileStage = 'pending' | 'downloading' | 'probing' | 'transcoding' | 'upload_queued' | 'uploading' | 'completed' | 'failed' | 'interrupted' | 'skipped'
export type CompanionStage = 'pending' | 'copying' | 'completed' | 'failed' | 'interrupted' | 'skipped'
export type CompanionFilePolicy = 'none' | 'subtitles' | 'all_non_video'
export type HardwareMode = 'mpp_mpp' | 'cpu_mpp' | 'cpu_cpu'
export type StorageKind = 'local' | 'rclone'

export interface StorageLocation { kind: StorageKind; path: string; remote?: string | null }
export interface TranscodeParams {
  hardwareMode: HardwareMode
  autoFallback: boolean
  videoCodec: 'h264' | 'hevc'
  container: 'mp4' | 'mkv'
  height: -1 | 360 | 480 | 720 | 1080 | 2160
  bitrateKbps: number
  smartBitrateCap: boolean
  frameRate: 'source' | '24' | '25' | '30' | '50' | '60'
  gop: number
  audioStrategy: 'copy' | 'aac' | 'drop'
  subtitleStrategy: 'auto' | 'copy' | 'drop'
}

export interface ParameterReason { field: string; code: string; message: string }
export interface ParameterDecision {
  source: Record<string, unknown> | null
  requested: Record<string, unknown> | null
  effective: Record<string, unknown> | null
  reasons: ParameterReason[]
  ffmpegArgv?: string[] | null
}

export interface TranscodeProgress {
  taskId: string
  fileId: string
  stage: 'transcoding'
  frame: number | null
  fps: number | null
  bitrateKbps: number | null
  outTimeMs: number | null
  totalSizeBytes: number | null
  speed: number | null
  percent: number | null
  etaSeconds: number | null
  progress: 'continue' | 'end'
  updatedAt: string
}

export interface TaskFile {
  id: string
  taskId: string
  relativePath: string
  stage: FileStage
  attempt: number
  sourceSize: number | null
  finalOutputPath: string | null
  artifactSize: number | null
  progress: TranscodeProgress | null
  parameterDecision?: ParameterDecision | null
  lastError: string | null
  lastExitCode: number | null
  version: number
  startedAt: string | null
  finishedAt: string | null
  updatedAt: string
}

export interface CompanionFile {
  id: string
  taskId: string
  relativePath: string
  category: string
  stage: CompanionStage
  attempt: number
  sourceSize: number | null
  finalOutputPath: string | null
  lastError: string | null
  version: number
  updatedAt: string
}

export interface Task {
  id: string
  name: string
  status: TaskStatus
  source: StorageLocation
  destination: StorageLocation
  requestedParams: TranscodeParams
  companionFilePolicy: CompanionFilePolicy
  totalFiles: number
  completedFiles: number
  failedFiles: number
  skippedFiles: number
  companionTotal: number
  companionCompleted: number
  companionFailed: number
  percent: number
  currentTranscodeFileId: string | null
  currentUploadFileId: string | null
  activeTranscodeFile?: TaskFile | null
  activeUploadFile?: TaskFile | CompanionFile | null
  uploadQueued?: number
  retryCount: number
  lastError: string | null
  interruptedReason: string | null
  version: number
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  updatedAt: string
}

export interface SystemStatus {
  ffmpegVersion: string | null
  ffprobeAvailable: boolean
  rcloneAvailable: boolean
  mppAvailable: boolean
  rgaAvailable: boolean
  encoders: string[]
  decoders: string[]
  filters: string[]
  devices: Record<string, boolean>
  error: string | null
  transcodeSlot: number
  uploadSlot: number
  uploadQueued: number
  cpuPercent?: number
  memoryPercent?: number
}

export interface Metrics {
  queuedTasks: number
  completedTasks: number
  completedVideos: number
  sourceBytes: number
  outputBytes: number
}

export interface Snapshot { tasks: Task[]; system: SystemStatus; metrics: Metrics }
export interface LogEntry { level: string; message: string; fileId: string | null; createdAt: string }
export interface ScanSummary {
  scanToken: string
  videoCount: number
  subtitleCount: number
  otherCount: number
  companionCount: number
  totalBytes: number
  expiresAt: string
}
export interface BrowseEntry { name: string; path: string; isDir: boolean; size: number | null; modifiedAt: string | null }
export interface ApiError { code: string; message: string; details?: unknown; requestId?: string }
export interface EventEnvelope<T = unknown> {
  id: string; type: string; version: number; taskId: string | null; fileId: string | null; updatedAt: string; payload: T
}
