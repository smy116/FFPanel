<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, CircleStop, Clock3, FileClock, Gauge, HardDriveDownload, LoaderCircle, RotateCcw, Trash2, UploadCloud, Zap } from 'lucide-vue-next'
import { api } from '../api'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import FileTable from '../components/FileTable.vue'
import { useTasksStore } from '../stores/tasks'
import type { CompanionFile, Task, TaskFile, TaskStatus } from '../types'

const store = useTasksStore()
const expandedId = ref<string | null>(null)
const files = ref<Record<string, TaskFile[]>>({})
const companions = ref<Record<string, CompanionFile[]>>({})
const logs = ref<Record<string, Array<{ level: string; message: string; createdAt: string }>>>({})
const dialog = ref<{ type: 'retry' | 'delete'; task: Task } | null>(null)
const busyId = ref('')
const actionError = ref('')
const completedPercent = computed(() => store.metrics.sourceBytes > 0 ? Math.max(0, Math.round((1 - store.metrics.outputBytes / store.metrics.sourceBytes) * 1000) / 10) : null)
const statusInfo: Record<TaskStatus, { label: string; tone: string }> = {
  queued: { label: '队列中', tone: 'neutral' }, running: { label: '运行中', tone: 'blue' },
  completed: { label: '已完成', tone: 'green' }, partial_failed: { label: '部分失败', tone: 'amber' },
  failed: { label: '已失败', tone: 'red' }, stopped: { label: '已停止', tone: 'red' },
  interrupted: { label: '已中断', tone: 'amber' },
}
const stageLabel: Record<string, string> = { pending: '等待中', downloading: '下载中', probing: '预检中', transcoding: '转码中', upload_queued: '待上传', uploading: '上传中', copying: '复制中', completed: '已完成', failed: '失败', interrupted: '中断', skipped: '跳过' }

onMounted(() => { void store.loadSnapshot(); store.connectEvents() })

async function toggleDetails(task: Task) {
  if (expandedId.value === task.id) { expandedId.value = null; return }
  expandedId.value = task.id
  if (!files.value[task.id]) {
    try {
      const [fileItems, companionItems, logItems] = await Promise.all([api.files(task.id), api.companions(task.id), api.logs(task.id)])
      files.value[task.id] = fileItems; companions.value[task.id] = companionItems; logs.value[task.id] = logItems
    } catch (reason) { actionError.value = reason instanceof Error ? reason.message : '详情加载失败' }
  }
}
async function stop(task: Task) {
  busyId.value = task.id; actionError.value = ''
  try { await store.stop(task.id) } catch (reason) { actionError.value = reason instanceof Error ? reason.message : '停止失败' }
  finally { busyId.value = '' }
}
async function confirmAction() {
  if (!dialog.value) return
  const { type, task } = dialog.value
  busyId.value = task.id; actionError.value = ''
  try {
    if (type === 'retry') await store.retry(task.id); else await store.remove(task.id)
    dialog.value = null
  } catch (reason) { actionError.value = reason instanceof Error ? reason.message : '操作失败' }
  finally { busyId.value = '' }
}
function formatLocation(task: Task, side: 'source' | 'destination') { const value = task[side]; return value.kind === 'local' ? value.path : `${value.remote}:${value.path}` }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) }
function formatBytes(value: number) { if (!value) return '0 B'; const units = ['B','KB','MB','GB','TB']; const i = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4); return `${(value / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}` }
function eta(seconds: number | null | undefined) { if (seconds == null) return 'ETA --'; const minutes = Math.floor(seconds / 60); return `ETA ${minutes ? `${minutes}m ` : ''}${seconds % 60}s` }
</script>

<template>
  <section>
    <div class="page-heading"><div><p class="eyebrow">TASK DASHBOARD</p><h1>任务清单</h1><p>FFmpeg 严格单并发，上传可与下一文件转码并行。</p></div><div class="live-chip" :class="{ online: store.connected }"><i></i>{{ store.connected ? '实时同步' : '正在重连' }}</div></div>
    <div v-if="store.interruptedCount" class="recovery-banner"><AlertTriangle :size="19" /><div><b>检测到 {{ store.interruptedCount }} 个上次未完成任务</b><span>任务已安全标记为中断，可从文件级检查点 Retry。</span></div></div>
    <div v-if="store.error || actionError" class="form-error"><AlertTriangle :size="16" />{{ actionError || store.error }}</div>
    <div class="metric-grid">
      <article><Activity /><span>转码槽位</span><strong>{{ store.system.transcodeSlot }} / 1</strong><small>{{ store.system.transcodeSlot ? 'FFmpeg 工作中' : '等待任务' }}</small></article>
      <article><UploadCloud /><span>上传槽位</span><strong>{{ store.system.uploadSlot }} / 1</strong><small>待上传 {{ store.system.uploadQueued }}</small></article>
      <article><Clock3 /><span>排队任务</span><strong>{{ store.metrics.queuedTasks }}</strong><small>{{ store.system.uploadQueued ? '含待上传文件' : '按创建时间 FIFO' }}</small></article>
      <article><CheckCircle2 /><span>已完成任务</span><strong>{{ store.metrics.completedTasks }}</strong><small>{{ store.metrics.completedVideos }} 个视频</small></article>
      <article><HardDriveDownload /><span>节省存储</span><strong>{{ completedPercent == null ? '--' : `${completedPercent}%` }}</strong><small>{{ formatBytes(store.metrics.sourceBytes) }} → {{ formatBytes(store.metrics.outputBytes) }}</small></article>
    </div>

    <div v-if="store.loading && !store.tasks.length" class="empty-card"><LoaderCircle class="spin" :size="28" /><h2>正在读取任务状态</h2></div>
    <div v-else-if="!store.tasks.length" class="empty-card"><div class="empty-icon"><Activity :size="28" /></div><h2>还没有转码任务</h2><p>创建任务后，转码与上传进度会实时显示在这里。</p><RouterLink to="/new" class="primary-button">创建第一个任务</RouterLink></div>

    <div v-else class="task-list">
      <article v-for="task in store.tasks" :key="task.id" class="task-card" :class="`task-${task.status}`">
        <header class="task-header">
          <div class="task-title"><div class="task-icon"><Zap v-if="task.requestedParams.hardwareMode !== 'cpu_cpu'" :size="19" /><Gauge v-else :size="19" /></div><div><div class="task-name-row"><h2>{{ task.name }}</h2><span class="status-badge" :class="statusInfo[task.status].tone">{{ statusInfo[task.status].label }}</span><span v-if="task.retryCount" class="retry-badge">Retry #{{ task.retryCount }}</span></div><p><code>{{ task.id.slice(0, 8) }}</code> · {{ formatDate(task.createdAt) }} · {{ task.requestedParams.hardwareMode === 'cpu_cpu' ? 'CPU' : 'MPP Hardware' }} / {{ task.requestedParams.videoCodec.toUpperCase() }}</p></div></div>
          <div class="path-summary"><span :title="formatLocation(task, 'source')">{{ formatLocation(task, 'source') }}</span><b>→</b><span :title="formatLocation(task, 'destination')">{{ formatLocation(task, 'destination') }}</span></div>
        </header>
        <div v-if="task.status === 'interrupted'" class="interrupted-note"><FileClock :size="17" /><div><b>上次运行被中断</b><span>{{ task.interruptedReason || '容器或进程非正常退出' }} · 已完成 {{ task.completedFiles }}/{{ task.totalFiles }}</span></div></div>
        <div class="task-progress-head"><span>{{ task.completedFiles }} / {{ task.totalFiles }} 视频完成</span><b>{{ task.percent.toFixed(0) }}%</b></div>
        <div class="progress-track"><i class="progress-success" :style="{ width: `${task.totalFiles ? task.completedFiles / task.totalFiles * 100 : 0}%` }"></i><i class="progress-error" :style="{ width: `${task.totalFiles ? task.failedFiles / task.totalFiles * 100 : 0}%` }"></i></div>
        <div class="count-row"><span>成功 {{ task.completedFiles }}</span><span>失败 {{ task.failedFiles }}</span><span>跳过 {{ task.skippedFiles }}</span><span v-if="task.companionTotal">伴随文件 {{ task.companionCompleted }}/{{ task.companionTotal }}</span></div>

        <div v-if="task.activeTranscodeFile || task.activeUploadFile || task.uploadQueued" class="pipeline-grid">
          <div v-if="task.activeTranscodeFile" class="pipeline-card transcode"><div class="pipeline-title"><Activity :size="17" /><b>转码槽位</b><span>{{ stageLabel[task.activeTranscodeFile.stage] }}</span></div><strong :title="task.activeTranscodeFile.relativePath">{{ task.activeTranscodeFile.relativePath }}</strong><div v-if="task.activeTranscodeFile.progress" class="mini-progress"><div class="progress-track" :class="{ indeterminate: task.activeTranscodeFile.progress.percent == null }"><i v-if="task.activeTranscodeFile.progress.percent != null" :style="{ width: `${task.activeTranscodeFile.progress.percent}%` }"></i></div><div><span>{{ task.activeTranscodeFile.progress.percent == null ? '进度未知' : `${task.activeTranscodeFile.progress.percent}%` }}</span><span>{{ task.activeTranscodeFile.progress.speed?.toFixed(1) || '--' }}x · {{ task.activeTranscodeFile.progress.fps?.toFixed(0) || '--' }} FPS · {{ eta(task.activeTranscodeFile.progress.etaSeconds) }}</span></div></div><p v-else>正在准备媒体文件…</p></div>
          <div v-if="task.activeUploadFile || task.uploadQueued" class="pipeline-card upload"><div class="pipeline-title"><UploadCloud :size="17" /><b>上传槽位</b><span>{{ task.activeUploadFile ? stageLabel[task.activeUploadFile.stage] : '等待中' }}</span></div><strong v-if="task.activeUploadFile" :title="task.activeUploadFile.relativePath">{{ task.activeUploadFile.relativePath }}</strong><p>待上传 {{ task.uploadQueued || 0 }} · 传输与 FFmpeg 独立运行</p></div>
        </div>
        <div v-if="task.lastError" class="task-error"><AlertTriangle :size="15" />{{ task.lastError }}</div>
        <footer class="task-actions">
          <button class="details-button" @click="toggleDetails(task)"><ChevronUp v-if="expandedId === task.id" :size="16" /><ChevronDown v-else :size="16" />{{ expandedId === task.id ? '收起详情' : '文件、参数与日志' }}</button>
          <div><button v-if="['queued','running'].includes(task.status)" class="secondary-button" :disabled="busyId === task.id" @click="stop(task)"><CircleStop :size="16" />停止</button><button v-if="['interrupted','failed','partial_failed','stopped'].includes(task.status)" class="secondary-button" @click="dialog = { type: 'retry', task }"><RotateCcw :size="16" />Retry</button><button class="icon-button danger" title="删除任务" @click="dialog = { type: 'delete', task }"><Trash2 :size="16" /></button></div>
        </footer>
        <div v-if="expandedId === task.id" class="task-details">
          <FileTable :files="files[task.id] || []" :companions="companions[task.id] || []" />
          <details class="log-panel"><summary>诊断日志 · 最近 {{ logs[task.id]?.length || 0 }} 条</summary><div><p v-for="(line, index) in logs[task.id] || []" :key="index"><time>{{ formatDate(line.createdAt) }}</time><span :class="line.level">{{ line.message }}</span></p><p v-if="!logs[task.id]?.length" class="muted-copy">暂无诊断日志</p></div></details>
        </div>
      </article>
    </div>
    <ConfirmDialog v-if="dialog" :open="true" :title="dialog.type === 'retry' ? '从安全检查点 Retry？' : '删除这个任务？'" :description="dialog.type === 'retry' ? '已完成文件不会重复处理；转码中断文件会重新预检和转码，完整待上传产物只会重新上传。FFmpeg 不能从中间帧续传。' : '任务记录、缓存和未完成的 .part 文件将被删除；已经生成或上传的正式输出会保留。'" :confirm-label="dialog.type === 'retry' ? '确认 Retry' : '删除任务'" :danger="dialog.type === 'delete'" :busy="busyId === dialog.task.id" @update:open="!$event && (dialog = null)" @confirm="confirmAction" />
  </section>
</template>
