import type { HardwareBackend, HardwareMode, HardwareProfile, SystemStatus, TranscodeParams } from './types'

export const modeLabels: Record<HardwareMode, string> = {
  mpp_mpp: 'Rockchip MPP 硬件编解码', cpu_mpp: 'CPU 软解 + MPP 编码', cpu_cpu: 'CPU 软件编解码',
  nvdec_nvenc: 'NVIDIA NVDEC + NVENC', cpu_nvenc: 'CPU 软解 + NVIDIA NVENC',
  qsv_qsv: 'Intel QSV 硬件编解码', cpu_qsv: 'CPU 软解 + Intel QSV',
  vaapi_vaapi: 'Intel VAAPI 硬件编解码', cpu_vaapi: 'CPU 软解 + Intel VAAPI',
}
export function modeLabel(mode: string, profiles: HardwareProfile[] = []): string {
  return profiles.find((profile) => profile.id === mode)?.label || modeLabels[mode as HardwareMode] || mode
}

// Older snapshots have only MPP/RGA flags. Keep their task history and UI usable.
export function hardwareProfiles(system: SystemStatus): HardwareProfile[] {
  if (system.hardwareProfiles?.length) return system.hardwareProfiles
  return (['mpp_mpp', 'cpu_mpp', 'cpu_cpu'] as const).map((id, index) => ({
    id, label: modeLabels[id], backendId: id === 'cpu_cpu' ? 'cpu' : 'rockchip',
    decodeMode: id === 'mpp_mpp' ? 'hardware' : 'software',
    fallback: (['cpu_mpp', 'cpu_cpu', null] as const)[index], detected: true,
    available: id === 'cpu_cpu' || system.mppAvailable,
    codecs: id === 'cpu_cpu' || system.mppAvailable ? ['h264', 'hevc'] : [],
    reason: id === 'cpu_cpu' || system.mppAvailable ? null : 'MPP/RGA 当前不可用',
  }))
}

export function recommendedMode(profiles: HardwareProfile[], codec: TranscodeParams['videoCodec']): HardwareMode {
  const order: HardwareMode[] = ['nvdec_nvenc', 'cpu_nvenc', 'qsv_qsv', 'cpu_qsv', 'vaapi_vaapi', 'cpu_vaapi', 'mpp_mpp', 'cpu_mpp', 'cpu_cpu']
  return order.find((mode) => profiles.some((profile) => profile.id === mode && profile.available && profile.codecs.includes(codec))) || 'cpu_cpu'
}

export function fallbackDescription(mode: HardwareMode, profiles: HardwareProfile[]): string {
  const labels: string[] = []
  const seen = new Set<string>([mode])
  let next = profiles.find((profile) => profile.id === mode)?.fallback
  while (next && !seen.has(next)) {
    seen.add(next)
    labels.push(modeLabel(next, profiles))
    next = profiles.find((profile) => profile.id === next)?.fallback
  }
  return labels.length ? `失败后依次尝试 ${labels.join('、')}` : '当前已是最终软件档位，不会继续退回'
}

export interface HardwareGroup { id: string; label: string; status: HardwareBackend['status']; details: string[] }
const stateLabels = { detecting: 'Detecting', ready: 'Ready', partial: 'Partial', unavailable: 'Unavailable' }
export function statusLabel(status: HardwareBackend['status']) { return stateLabels[status] }
export function hardwareGroups(system: SystemStatus): HardwareGroup[] {
  const backends = system.hardwareBackends
  if (!backends?.length) {
    if (!system.ffmpegVersion && !system.error) return [{ id: 'cpu', label: '硬件', status: 'detecting', details: ['正在检测硬件能力'] }]
    if (system.mppAvailable || system.rgaAvailable) return [{ id: 'rockchip', label: 'MPP', status: system.mppAvailable && system.rgaAvailable ? 'ready' : 'partial', details: [`MPP · ${system.mppAvailable ? 'Ready' : 'Unavailable'}`, `RGA · ${system.rgaAvailable ? 'Ready' : 'Unavailable'}`] }]
    return [{ id: 'cpu', label: 'CPU', status: system.ffmpegVersion ? 'ready' : 'unavailable', details: [system.error || 'CPU 软件编解码'] }]
  }
  const visible = backends.filter((backend) => backend.detected && backend.id !== 'cpu')
  if (!visible.length) visible.push(...backends.filter((backend) => backend.id === 'cpu'))
  const groups = new Map<string, HardwareGroup>()
  for (const backend of visible) {
    const group = groups.get(backend.group) || { id: backend.group, label: backend.group === 'intel' ? 'Intel QSV/VAAPI' : backend.label, status: backend.status, details: [] }
    if (group.status !== backend.status) group.status = 'partial'
    group.details.push(`${backend.label} · ${statusLabel(backend.status)}${backend.device ? ` · ${backend.device}` : ''}`)
    const featureLabels: Record<string, string> = { mpp: 'MPP', rga: 'RGA', decode: backend.id === 'nvidia' ? 'NVDEC' : '硬件解码', encode_h264: 'H.264 编码', encode_hevc: 'HEVC 编码', scale: '硬件缩放' }
    for (const [key, label] of Object.entries(featureLabels)) {
      if (key in backend.features) group.details.push(`${label} · ${backend.features[key] ? 'Ready' : 'Unavailable'}`)
    }
    group.details.push(...Object.values(backend.errors))
    groups.set(backend.group, group)
  }
  return [...groups.values()]
}
