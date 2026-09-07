import { describe, expect, it } from 'vitest'
import { fallbackDescription, hardwareGroups, hardwareProfiles, modeLabel, recommendedMode } from './hardware'
import type { HardwareBackend, HardwareProfile, SystemStatus } from './types'

const cpu: HardwareProfile = { id: 'cpu_cpu', label: 'CPU', backendId: 'cpu', decodeMode: 'software', detected: true, available: true, codecs: ['h264', 'hevc'] }
const nvidia: HardwareProfile = { id: 'nvdec_nvenc', label: 'NVDEC + NVENC', backendId: 'nvidia', decodeMode: 'hardware', fallback: 'cpu_nvenc', detected: true, available: true, codecs: ['h264'] }
const profiles: HardwareProfile[] = [cpu, nvidia,
  { ...nvidia, id: 'cpu_nvenc', label: 'CPU + NVENC', decodeMode: 'software', fallback: 'cpu_cpu' },
  { ...nvidia, id: 'qsv_qsv', label: 'QSV', backendId: 'qsv', codecs: ['h264', 'hevc'], fallback: 'cpu_cpu' }]
const system: SystemStatus = { ffmpegVersion: 'test', ffprobeAvailable: true, rcloneAvailable: false,
  mppAvailable: false, rgaAvailable: false, encoders: ['libx264', 'libx265'], decoders: [], filters: [], devices: {}, error: null,
  transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0 }
function backend(id: string, status: HardwareBackend['status'] = 'ready'): HardwareBackend {
  return { id, group: ['qsv', 'vaapi'].includes(id) ? 'intel' : id, label: id === 'nvidia' ? 'NVENC' : id,
    status, detected: true, features: {}, errors: {}, encoders: [], decoders: [], filters: [] }
}

describe('hardware presentation', () => {
  it('recommends by output codec and retains legacy labels', () => {
    expect(recommendedMode(profiles, 'h264')).toBe('nvdec_nvenc')
    expect(recommendedMode(profiles, 'hevc')).toBe('qsv_qsv')
    expect(modeLabel('cpu_mpp')).toContain('MPP')
    expect(modeLabel('cpu_nvenc')).toContain('NVENC')
    expect(modeLabel('unknown')).toBe('unknown')
    expect(hardwareProfiles(system).map(profile => profile.id)).toContain('cpu_cpu')
  })
  it('takes dynamic profiles and fallback labels from the backend', () => {
    expect(hardwareProfiles({ ...system, hardwareProfiles: profiles })).toEqual(profiles)
    expect(fallbackDescription('nvdec_nvenc', profiles)).toBe('失败后依次尝试 CPU + NVENC、CPU')
  })
  it('combines Intel APIs and preserves unavailable diagnostics with mixed GPUs', () => {
    const groups = hardwareGroups({ ...system, hardwareBackends: [backend('cpu'), backend('nvidia'),
      { ...backend('qsv', 'unavailable'), errors: { initialize: 'driver missing' } }, backend('vaapi')] })
    expect(groups.map(group => group.label)).toEqual(['Rockchip MPP', 'Intel QSV/VAAPI', 'NVIDIA NVENC'])
    expect(groups[1]?.status).toBe('partial')
    expect(groups[1]?.detailSections).toHaveLength(2)
    expect(groups[1]?.detailSections[0]?.[0]).toContain('qsv')
    expect(groups[1]?.detailSections[1]?.[0]).toContain('vaapi')
    expect(groups[1]?.detailSections.flat()).toContain('driver missing')
  })
  it('keeps undetected hardware visible as unavailable and omits CPU', () => {
    const groups = hardwareGroups({ ...system, hardwareBackends: [backend('cpu'), { ...backend('nvidia', 'unavailable'), detected: false }] })
    expect(groups.map(group => group.id)).toEqual(['rockchip', 'intel', 'nvidia'])
    expect(groups[2]?.status).toBe('unavailable')
  })
  it('does not leave failed detection in Detecting state', () => {
    expect(hardwareGroups({ ...system, ffmpegVersion: null, error: 'ffmpeg missing' }).map(group => group.status)).toEqual(['unavailable', 'unavailable', 'unavailable'])
    expect(hardwareGroups({ ...system, ffmpegVersion: null }).map(group => group.status)).toEqual(['detecting', 'detecting', 'detecting'])
  })
  it('preserves MPP and RGA partial states', () => {
    const group = hardwareGroups({ ...system, mppAvailable: true })[0]
    expect(group?.label).toBe('Rockchip MPP')
    expect(group?.status).toBe('partial')
    expect(group?.detailSections.flat()).toContain('RGA · Unavailable')
  })

  it('reports ready Rockchip and unavailable Intel and NVIDIA for a legacy RK3588 snapshot', () => {
    const groups = hardwareGroups({ ...system, mppAvailable: true, rgaAvailable: true })
    expect(groups.map(group => group.status)).toEqual(['ready', 'unavailable', 'unavailable'])
  })

  it('returns no recommendation when the selected codec has no usable profile', () => {
    expect(recommendedMode(profiles.map(profile => ({ ...profile, available: false })), 'hevc')).toBeNull()
  })
})
