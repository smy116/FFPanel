<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Cpu, FolderOpen, Gauge, HardDrive, LoaderCircle, ScanSearch, Server, Settings2, Subtitles, Zap } from 'lucide-vue-next'
import { api } from '../api'
import PathBrowserDialog from '../components/PathBrowserDialog.vue'
import { useTasksStore } from '../stores/tasks'
import type { CompanionFilePolicy, HardwareMode, ScanSummary, StorageLocation, TranscodeParams } from '../types'
import { registerTaskTool } from '../webmcp'

const router = useRouter()
const store = useTasksStore()
const step = ref(1)
const error = ref('')
const busy = ref(false)
const scan = ref<ScanSummary | null>(null)
const customBitrate = ref(false)
const browserOpen = ref(false)
const browsing = ref<'source' | 'destination'>('source')
const form = reactive({
  name: '', source: { kind: 'local', path: '/media/incoming', remote: null } as StorageLocation,
  destination: { kind: 'local', path: '/media/encoded', remote: null } as StorageLocation,
  companionFilePolicy: 'subtitles' as CompanionFilePolicy,
  params: {
    hardwareMode: 'mpp_mpp', autoFallback: true, videoCodec: 'hevc', container: 'mp4', height: 720,
    bitrateKbps: 2000, smartBitrateCap: true, frameRate: 'source', rateControl: 'vbr',
    audioStrategy: 'copy', subtitleStrategy: 'auto',
  } as TranscodeParams,
})
const steps = [
  ['路径与存储', '输入与输出位置'], ['编解码方案', '硬件与格式'],
  ['画质策略', '分辨率与码率'], ['确认并启动', '扫描与预检'],
]
const browserLocation = computed(() => form[browsing.value])
const sourceLabel = computed(() => formatLocation(form.source))
const destinationLabel = computed(() => formatLocation(form.destination))
const policyLabel = computed(() => ({ none: '不复制', subtitles: '仅复制字幕', all_non_video: '复制全部非视频文件' })[form.companionFilePolicy])
const modeLabel = computed(() => ({ mpp_mpp: 'MPP 硬件解码 + 编码', cpu_mpp: 'CPU 解码 + MPP 编码', cpu_cpu: 'CPU 软件编解码' })[form.params.hardwareMode])
const fallbackDescription = computed(() => ({
  mpp_mpp: '失败后依次尝试 CPU 软解 + MPP 编码、CPU 软件编解码',
  cpu_mpp: '失败后继续尝试 CPU 软件编解码',
  cpu_cpu: '当前已是最终软件档位，不会继续退回',
})[form.params.hardwareMode])
const mppWarning = computed(() => {
  if (form.params.hardwareMode === 'cpu_cpu') return 'MPP/RGA 当前不可用，当前 CPU 软件编解码方案不受影响。'
  return form.params.autoFallback
    ? 'MPP/RGA 当前不可用，将自动尝试可用的后续档位。'
    : 'MPP/RGA 当前不可用，请开启自动退回或选择 CPU 软件编解码。'
})
let unregisterTool: () => void = () => undefined

onMounted(async () => { await Promise.all([store.loadRemotes(), store.loadSnapshot()]); unregisterTool = registerTaskTool() })
onBeforeUnmount(() => unregisterTool())
watch(() => [form.source.kind, form.source.path, form.source.remote, form.companionFilePolicy], () => { scan.value = null })

function setKind(target: 'source' | 'destination', kind: 'local' | 'rclone') {
  const location = form[target]
  location.kind = kind
  location.path = kind === 'local' ? (target === 'source' ? '/media/incoming' : '/media/encoded') : ''
  location.remote = kind === 'rclone' ? store.remotes[0] || null : null
}
function openBrowser(target: 'source' | 'destination') { browsing.value = target; browserOpen.value = true }
function formatLocation(location: StorageLocation) { return location.kind === 'local' ? location.path : `${location.remote || '未选择'}:${location.path}` }
function validate(current = step.value): boolean {
  error.value = ''
  if (current === 1) {
    if (!form.source.path || !form.destination.path) error.value = '请填写输入和输出路径。'
    else if ((form.source.kind === 'rclone' && !form.source.remote) || (form.destination.kind === 'rclone' && !form.destination.remote)) error.value = '远程存储必须选择 Remote。'
    else if (sourceLabel.value === destinationLabel.value) error.value = '输入和输出位置不能相同。'
  }
  if (current === 2 && form.params.hardwareMode !== 'cpu_cpu' && !store.system.mppAvailable && !form.params.autoFallback) error.value = '当前未检测到可用的 MPP/RGA 能力，请开启自动退回或选择 CPU 软件编解码。'
  if (current === 3 && (form.params.bitrateKbps < 100 || form.params.bitrateKbps > 100000)) error.value = '目标码率必须在 100–100000 kbps 之间。'
  return !error.value
}
function next() { if (validate()) step.value = Math.min(4, step.value + 1) }
function previous() { error.value = ''; step.value = Math.max(1, step.value - 1) }
async function runScan() {
  if (!validate(1)) return
  busy.value = true; error.value = ''
  try { scan.value = await api.scan(form.source, form.companionFilePolicy) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '扫描失败' }
  finally { busy.value = false }
}
async function createTask() {
  if (!scan.value) { error.value = '请先完成扫描。'; return }
  busy.value = true; error.value = ''
  try {
    const task = await api.createTask({
      name: form.name || undefined, source: form.source, destination: form.destination,
      scanToken: scan.value.scanToken, companionFilePolicy: form.companionFilePolicy, params: form.params,
    })
    store.replaceTask(task)
    await router.push('/tasks')
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '任务创建失败' }
  finally { busy.value = false }
}
function formatBytes(value: number) {
  if (!value) return '0 B'; const units = ['B', 'KB', 'MB', 'GB', 'TB']; const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`
}
</script>

<template>
  <section>
    <div class="page-heading">
      <div><p class="eyebrow">NEW TRANSCODE JOB</p><h1>创建转码任务</h1><p>配置路径与参数，将一批视频加入持久化流水线。</p></div>
      <div class="step-caption"><strong>{{ step }}</strong><span>{{ steps[step - 1]?.[0] }}</span><small>第 {{ step }} 步，共 4 步</small></div>
    </div>
    <ol class="stepper" aria-label="任务创建进度">
      <li v-for="(item, index) in steps" :key="item[0]" :class="{ active: step === index + 1, done: step > index + 1 }" @click="index + 1 < step && (step = index + 1)">
        <span><Check v-if="step > index + 1" :size="15" />{{ step <= index + 1 ? index + 1 : '' }}</span><div><b>{{ item[0] }}</b><small>{{ item[1] }}</small></div>
      </li>
    </ol>

    <div class="wizard-card">
      <template v-if="step === 1">
        <div class="section-title"><div class="icon-tile"><FolderOpen :size="20" /></div><div><h2>媒体路径</h2><p>本地目录限制在容器已挂载的媒体根目录中。</p></div></div>
        <div class="path-grid">
          <article v-for="target in (['source', 'destination'] as const)" :key="target" class="path-panel">
            <label class="field-label">{{ target === 'source' ? '输入来源' : '输出位置' }}</label>
            <div class="segmented">
              <button :class="{ selected: form[target].kind === 'local' }" @click="setKind(target, 'local')"><HardDrive :size="17" />本地存储</button>
              <button :class="{ selected: form[target].kind === 'rclone' }" :disabled="!store.remotes.length" @click="setKind(target, 'rclone')"><Server :size="17" />Rclone</button>
            </div>
            <template v-if="form[target].kind === 'rclone'"><label class="field-label">Remote</label><select v-model="form[target].remote" class="select-input"><option v-for="remote in store.remotes" :key="remote" :value="remote">{{ remote }}:</option></select></template>
            <label class="field-label">{{ target === 'source' ? '源文件或目录' : '目标根目录' }}</label>
            <div class="input-action"><input v-model="form[target].path" :placeholder="form[target].kind === 'local' ? '/media/...' : '目录/子目录'" /><button :aria-label="target === 'source' ? '浏览源文件或目录' : '浏览目标根目录'" title="浏览" @click="openBrowser(target)"><FolderOpen :size="18" /></button></div>
          </article>
          <div class="flow-arrow"><ArrowRight :size="20" /></div>
        </div>
        <div v-if="!store.remotes.length" class="inline-notice"><AlertTriangle :size="16" />未发现 rclone 配置，远程存储暂不可用；本地转码不受影响。</div>
        <div class="divider"></div>
        <div class="section-title compact"><div class="icon-tile green"><Subtitles :size="20" /></div><div><h2>伴随文件</h2><p>复制时保留相对目录结构，已有目标文件不会被覆盖。</p></div></div>
        <div class="radio-cards">
          <label v-for="choice in [{ value: 'none', title: '不复制', note: '只处理视频文件' }, { value: 'subtitles', title: '仅复制字幕', note: 'SRT、ASS、SSA、VTT' }, { value: 'all_non_video', title: '复制其他文件', note: '字幕、封面、NFO 与文本' }]" :key="choice.value" :class="{ selected: form.companionFilePolicy === choice.value }">
            <input v-model="form.companionFilePolicy" type="radio" :value="choice.value" /><span><b>{{ choice.title }} <em v-if="choice.value === 'subtitles'">默认</em></b><small>{{ choice.note }}</small></span>
          </label>
        </div>
      </template>

      <template v-else-if="step === 2">
        <div class="section-title"><div class="icon-tile green"><Zap :size="20" /></div><div><h2>硬件加速与编解码方案</h2><p>可按显式策略逐级退回，每次实际选择都会记录在任务详情中。</p></div></div>
        <div v-if="!store.system.mppAvailable" class="inline-notice warning"><AlertTriangle :size="16" />{{ mppWarning }}</div>
        <div class="profile-cards">
          <button v-for="profile in [{ value: 'mpp_mpp', title: 'Rockchip MPP 硬件编解码', note: '最快 · 低功耗 · 优先零拷贝', icon: Zap }, { value: 'cpu_mpp', title: 'CPU 软解 + MPP 编码', note: '兼容特殊或旧视频源', icon: Cpu }, { value: 'cpu_cpu', title: 'CPU 软件编解码', note: '通用降级方案', icon: Settings2 }]" :key="profile.value" :disabled="profile.value !== 'cpu_cpu' && !store.system.mppAvailable && !form.params.autoFallback" :class="{ selected: form.params.hardwareMode === profile.value }" @click="form.params.hardwareMode = profile.value as HardwareMode">
            <component :is="profile.icon" :size="22" /><span><b>{{ profile.title }}</b><small>{{ profile.note }}</small></span><i v-if="profile.value === 'mpp_mpp'">推荐</i>
          </button>
        </div>
        <label class="switch-card fallback-card"><input v-model="form.params.autoFallback" type="checkbox" /><span class="switch-ui"></span><span><b>转码自动退回</b><small>{{ fallbackDescription }}</small></span></label>
        <div class="choice-grid">
          <div><label class="field-label">输出视频编码</label><div class="segmented large"><button :class="{ selected: form.params.videoCodec === 'hevc' }" @click="form.params.videoCodec = 'hevc'">HEVC / H.265</button><button :class="{ selected: form.params.videoCodec === 'h264' }" @click="form.params.videoCodec = 'h264'">H.264 / AVC</button></div></div>
          <div><label class="field-label">输出封装格式</label><div class="segmented large"><button :class="{ selected: form.params.container === 'mp4' }" @click="form.params.container = 'mp4'">MP4 · 通用兼容</button><button :class="{ selected: form.params.container === 'mkv' }" @click="form.params.container = 'mkv'">MKV · 多流友好</button></div></div>
        </div>
      </template>

      <template v-else-if="step === 3">
        <div class="section-title"><div class="icon-tile"><Gauge :size="20" /></div><div><h2>智能分辨率与码率</h2><p>目标是质量上限，决策器不会主动提高源视频规格。</p></div></div>
        <label class="field-label">目标分辨率高度</label>
        <div class="pill-group"><button v-for="height in [-1, 2160, 1080, 720, 480, 360] as const" :key="height" :class="{ selected: form.params.height === height }" @click="form.params.height = height">{{ height === -1 ? '保持原高度' : `${height}p` }}<em v-if="height === 720">默认</em></button></div>
        <div class="strategy-block"><div><label class="field-label">目标码率上限</label><div class="pill-group"><button v-for="rate in [1000, 2000, 4000, 6000]" :key="rate" :class="{ selected: !customBitrate && form.params.bitrateKbps === rate }" @click="customBitrate = false; form.params.bitrateKbps = rate">{{ rate }} kbps</button><button :class="{ selected: customBitrate }" @click="customBitrate = true">自定义</button></div><input v-if="customBitrate" v-model.number="form.params.bitrateKbps" type="number" min="100" max="100000" class="number-input" /></div>
          <label class="switch-card"><input v-model="form.params.smartBitrateCap" type="checkbox" /><span class="switch-ui"></span><span><b>Smart Bitrate Cap</b><small>源码率较低时自动采用源码率</small></span></label>
        </div>
        <div class="advanced-grid"><label>帧率策略<select v-model="form.params.frameRate" class="select-input"><option value="source">保持源帧率</option><option v-for="fps in ['24','25','30','50','60']" :key="fps" :value="fps">{{ fps }} FPS</option></select></label><label>码率控制模式<select v-model="form.params.rateControl" class="select-input"><option value="vbr">VBR · 可变码率</option><option value="cbr">CBR · 恒定码率</option></select></label><label>音频策略<select v-model="form.params.audioStrategy" class="select-input"><option value="copy">复制音轨</option><option value="aac">转为 AAC</option><option value="drop">丢弃音频</option></select></label><label>字幕策略<select v-model="form.params.subtitleStrategy" class="select-input"><option value="auto">自动兼容</option><option value="copy">直接复制</option><option value="drop">丢弃字幕</option></select></label></div>
      </template>

      <template v-else>
        <div class="section-title"><div class="icon-tile"><ScanSearch :size="20" /></div><div><h2>预检确认与启动</h2><p>这里展示用户目标；单文件实际参数会在 ffprobe 后确定。</p></div></div>
        <label class="field-label">任务名称（可选）</label><input v-model="form.name" class="text-input" placeholder="不填写时使用输入目录名称" />
        <div class="summary-grid"><div><small>输入位置</small><b>{{ sourceLabel }}</b></div><div><small>输出位置</small><b>{{ destinationLabel }}</b></div><div><small>伴随文件</small><b>{{ policyLabel }}</b></div><div><small>编解码模式</small><b>{{ modeLabel }}</b></div><div><small>自动退回</small><b>{{ form.params.autoFallback ? '开启 · 按档位逐级尝试' : '关闭 · 仅使用指定模式' }}</b></div><div><small>目标格式</small><b>{{ form.params.videoCodec.toUpperCase() }} · {{ form.params.container.toUpperCase() }}</b></div><div><small>画质上限</small><b>{{ form.params.height === -1 ? '原始高度' : `${form.params.height}p` }} · {{ form.params.bitrateKbps }} kbps</b></div></div>
        <div class="scan-panel">
          <button class="secondary-button scan-button" :disabled="busy" @click="runScan"><LoaderCircle v-if="busy" class="spin" :size="17" /><ScanSearch v-else :size="17" />{{ busy ? '正在扫描…' : '扫描并统计' }}</button>
          <div v-if="scan" class="scan-results"><div><strong>{{ scan.videoCount }}</strong><span>视频文件</span></div><div><strong>{{ scan.subtitleCount }}</strong><span>字幕文件</span></div><div><strong>{{ scan.otherCount }}</strong><span>其他文件</span></div><div><strong>{{ scan.companionCount }}</strong><span>将复制</span></div><div><strong>{{ formatBytes(scan.totalBytes) }}</strong><span>扫描体积</span></div></div>
          <p v-else>远程扫描只读取文件元数据，不会批量下载或执行 ffprobe。</p>
        </div>
      </template>

      <p v-if="error" class="form-error"><AlertTriangle :size="16" />{{ error }}</p>
      <div class="wizard-actions"><button v-if="step > 1" class="secondary-button" @click="previous"><ArrowLeft :size="17" />返回上一步</button><span v-else>任务状态将持久化到 /config</span><button v-if="step < 4" class="primary-button" @click="next">下一步：{{ steps[step]?.[0] }} <ArrowRight :size="17" /></button><button v-else class="primary-button" :disabled="busy || !scan" @click="createTask"><LoaderCircle v-if="busy" class="spin" :size="17" /><Zap v-else :size="17" />立即加入转码队列</button></div>
    </div>
    <PathBrowserDialog v-model:open="browserOpen" :location="browserLocation" @select="form[browsing] = $event" />
  </section>
</template>
