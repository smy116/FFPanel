import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import NewTaskView from './NewTaskView.vue'

vi.mock('../api', () => ({ api: {
  remotes: vi.fn().mockResolvedValue({ items: [], available: false }),
  snapshot: vi.fn().mockResolvedValue({ tasks: [], metrics: { queuedTasks: 0, completedTasks: 0, completedVideos: 0, sourceBytes: 0, outputBytes: 0 }, system: { ffmpegVersion: 'test', ffprobeAvailable: true, rcloneAvailable: false, mppAvailable: true, rgaAvailable: true, encoders: [], decoders: [], filters: [], devices: {}, error: null, transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0 } }),
  browse: vi.fn(), scan: vi.fn(), createTask: vi.fn(),
} }))

describe('new task wizard', () => {
  beforeEach(() => { vi.clearAllMocks(); setActivePinia(createPinia()) })

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

  it('allows an unavailable MPP start only while fallback is enabled', async () => {
    vi.mocked(api.snapshot).mockResolvedValueOnce({ tasks: [], metrics: { queuedTasks: 0, completedTasks: 0, completedVideos: 0, sourceBytes: 0, outputBytes: 0 }, system: { ffmpegVersion: 'test', ffprobeAvailable: true, rcloneAvailable: false, mppAvailable: false, rgaAvailable: false, encoders: [], decoders: [], filters: [], devices: {}, error: null, transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0 } })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/new', component: NewTaskView }, { path: '/tasks', component: { template: '<div />' } }] })
    await router.push('/new'); await router.isReady()
    const wrapper = mount(NewTaskView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('下一步'))!.trigger('click')
    const mpp = wrapper.findAll('button').find((button) => button.text().includes('Rockchip MPP'))!
    expect(mpp.attributes('disabled')).toBeUndefined()
    const fallback = wrapper.findAll('label').find((label) => label.text().includes('转码自动退回'))!
    await fallback.find('input').setValue(false)
    expect(mpp.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('请开启自动退回或选择 CPU 软件编解码')
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

