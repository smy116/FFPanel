import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import NewTaskView from './NewTaskView.vue'
import { useTasksStore } from '../stores/tasks'
import type { HardwareProfile } from '../types'

vi.mock('../api', () => ({ api: {
  remotes: vi.fn().mockResolvedValue({ items: [], available: false }),
  snapshot: vi.fn().mockResolvedValue({ tasks: [], metrics: { queuedTasks: 0, completedTasks: 0, completedVideos: 0, sourceBytes: 0, outputBytes: 0 }, system: { ffmpegVersion: 'test', ffprobeAvailable: true, rcloneAvailable: false, mppAvailable: true, rgaAvailable: true, encoders: [], decoders: [], filters: [], devices: {}, error: null, transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0 } }),
  browse: vi.fn(), scan: vi.fn(), createTask: vi.fn(),
} }))

describe('new task wizard', () => {
  beforeEach(() => { vi.clearAllMocks(); setActivePinia(createPinia()) })

  it('selects dynamic GPU profiles and preserves manual choice across SSE updates', async () => {
    const profiles: HardwareProfile[] = [
      { id: 'nvdec_nvenc', label: 'NVDEC + NVENC', backendId: 'nvidia', decodeMode: 'hardware', detected: true, available: true, codecs: ['hevc'], fallback: 'cpu_cpu' },
      { id: 'qsv_qsv', label: 'Intel QSV', backendId: 'qsv', decodeMode: 'hardware', detected: true, available: true, codecs: ['h264', 'hevc'], fallback: 'cpu_cpu' },
      { id: 'cpu_cpu', label: 'CPU 软件编解码', backendId: 'cpu', decodeMode: 'software', detected: true, available: true, codecs: ['h264', 'hevc'] },
    ]
    const original = await api.snapshot()
    vi.mocked(api.snapshot).mockResolvedValueOnce({ ...original, system: { ...original.system, hardwareProfiles: profiles } })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('下一步'))!.trigger('click')
    const selected = () => wrapper.find('.profile-cards .selected').text()
    expect(selected()).toContain('NVDEC')
    expect(wrapper.text()).not.toContain('Rockchip')
    await wrapper.findAll('button').find(button => button.text() === 'H.264 / AVC')!.trigger('click')
    expect(selected()).toContain('Intel QSV')
    await wrapper.findAll('.profile-cards button').find(button => button.text().includes('CPU 软件编解码'))!.trigger('click')
    useTasksStore().mergeEvent({ id: 'gpu-update', type: 'system.status', version: 1, updatedAt: '', taskId: null, fileId: null, payload: { hardwareProfiles: profiles } })
    await flushPromises()
    expect(selected()).toContain('CPU 软件编解码')
    useTasksStore().mergeEvent({ id: 'gpu-update-2', type: 'system.status', version: 2, updatedAt: '', taskId: null, fileId: null, payload: { hardwareProfiles: profiles.map(profile => profile.id === 'cpu_cpu' ? { ...profile, available: false, codecs: [] } : profile) } })
    await flushPromises()
    expect(selected()).toContain('Intel QSV')
    wrapper.unmount()
  })

  it('shows only usable Rockchip and CPU profiles on RK3588', async () => {
    const profiles: HardwareProfile[] = [
      { id: 'mpp_mpp', label: 'Rockchip MPP 硬件编解码', backendId: 'rockchip', decodeMode: 'hardware', detected: true, available: true, codecs: ['h264', 'hevc'], fallback: 'cpu_mpp' },
      { id: 'cpu_mpp', label: 'CPU 软解 + MPP 编码', backendId: 'rockchip', decodeMode: 'software', detected: true, available: true, codecs: ['h264', 'hevc'], fallback: 'cpu_cpu' },
      { id: 'qsv_qsv', label: 'Intel QSV 硬件编解码', backendId: 'qsv', decodeMode: 'hardware', detected: true, available: false, codecs: [], reason: '无法读取 Intel GPU 厂商信息' },
      { id: 'vaapi_vaapi', label: 'Intel VAAPI 硬件编解码', backendId: 'vaapi', decodeMode: 'hardware', detected: true, available: false, codecs: [], reason: '设备初始化失败' },
      { id: 'nvdec_nvenc', label: 'NVIDIA NVDEC + NVENC', backendId: 'nvidia', decodeMode: 'hardware', detected: false, available: false, codecs: [], reason: '未检测到 NVIDIA 设备' },
      { id: 'cpu_cpu', label: 'CPU 软件编解码', backendId: 'cpu', decodeMode: 'software', detected: true, available: true, codecs: ['h264', 'hevc'] },
    ]
    const original = await api.snapshot()
    vi.mocked(api.snapshot).mockResolvedValueOnce({ ...original, system: { ...original.system, hardwareProfiles: profiles } })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('下一步'))!.trigger('click')
    expect(wrapper.text()).toContain('Rockchip MPP 硬件编解码')
    expect(wrapper.text()).toContain('CPU 软件编解码')
    expect(wrapper.text()).not.toContain('Intel QSV')
    expect(wrapper.text()).not.toContain('Intel VAAPI')
    expect(wrapper.text()).not.toContain('NVIDIA NVDEC')
  })

  it('keeps form state while moving through the four-step flow', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }, { path: '/tasks', component: { template: '<div />' } }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    const next = () => wrapper.findAll('button').find((button) => button.text().includes('下一步'))!
    await next().trigger('click')
    expect(wrapper.text()).toContain('硬件加速与编解码方案')
    await next().trigger('click')
    expect(wrapper.text()).toContain('智能分辨率与码率')
    expect(wrapper.text()).toContain('Smart Bitrate Cap')
    const rateControl = wrapper.findAll('label').find((label) => label.text().includes('码率控制模式'))!
    expect((rateControl.find('select').element as HTMLSelectElement).value).toBe('vbr')
    expect(rateControl.text()).toContain('CBR · 恒定码率')
  })

  it('enables automatic fallback by default', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }, { path: '/tasks', component: { template: '<div />' } }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('下一步'))!.trigger('click')
    const fallback = wrapper.findAll('label').find((label) => label.text().includes('转码自动退回'))!
    expect((fallback.find('input').element as HTMLInputElement).checked).toBe(true)
    expect(fallback.text()).toContain('CPU 软解 + MPP 编码')
  })

  it('hides unavailable MPP profiles even while fallback is enabled', async () => {
    vi.mocked(api.snapshot).mockResolvedValueOnce({ tasks: [], metrics: { queuedTasks: 0, completedTasks: 0, completedVideos: 0, sourceBytes: 0, outputBytes: 0 }, system: { ffmpegVersion: 'test', ffprobeAvailable: true, rcloneAvailable: false, mppAvailable: false, rgaAvailable: false, encoders: [], decoders: [], filters: [], devices: {}, error: null, transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0 } })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }, { path: '/tasks', component: { template: '<div />' } }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('下一步'))!.trigger('click')
    expect(wrapper.text()).not.toContain('Rockchip MPP')
    expect(wrapper.text()).not.toContain('CPU 软解 + MPP')
    expect(wrapper.text()).toContain('CPU 软件编解码')
  })

  it('shows an empty state and blocks progress when no profile supports the target codec', async () => {
    const unavailable: HardwareProfile[] = [
      { id: 'cpu_cpu', label: 'CPU 软件编解码', backendId: 'cpu', decodeMode: 'software', detected: true, available: false, codecs: [] },
      { id: 'qsv_qsv', label: 'Intel QSV', backendId: 'qsv', decodeMode: 'hardware', detected: true, available: false, codecs: [] },
    ]
    const original = await api.snapshot()
    vi.mocked(api.snapshot).mockResolvedValueOnce({ ...original, system: { ...original.system, hardwareProfiles: unavailable } })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('下一步'))!.trigger('click')
    expect(wrapper.text()).toContain('当前没有支持 HEVC 的可用编解码方案')
    expect(wrapper.find('.profile-cards').findAll('button')).toHaveLength(0)
    await wrapper.findAll('button').find(button => button.text().includes('下一步'))!.trigger('click')
    expect(wrapper.text()).toContain('当前没有可用于 HEVC 的编解码方案')
    expect(wrapper.text()).not.toContain('智能分辨率与码率')
  })

  it('submits the fallback choice with the task parameters', async () => {
    vi.mocked(api.scan).mockResolvedValueOnce({ scanToken: 'scan', videoCount: 1, subtitleCount: 0, otherCount: 0, companionCount: 0, totalBytes: 10, expiresAt: '' })
    vi.mocked(api.createTask).mockRejectedValueOnce(new Error('captured'))
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }, { path: '/tasks', component: { template: '<div />' } }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    for (let index = 0; index < 3; index += 1) {
      await wrapper.findAll('button').find((button) => button.text().includes('下一步'))!.trigger('click')
    }
    await wrapper.findAll('button').find((button) => button.text().includes('扫描并统计'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('立即加入转码队列'))!.trigger('click')
    await flushPromises()
    expect(api.createTask).toHaveBeenCalledWith(expect.objectContaining({ params: expect.objectContaining({ autoFallback: true }) }))
  })
})

