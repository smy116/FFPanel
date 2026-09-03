import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewTaskView from './NewTaskView.vue'

vi.mock('../api', () => ({ api: {
  remotes: vi.fn().mockResolvedValue({ items: [], available: false }),
  snapshot: vi.fn().mockResolvedValue({ tasks: [], metrics: { queuedTasks: 0, completedTasks: 0, completedVideos: 0, sourceBytes: 0, outputBytes: 0 }, system: { ffmpegVersion: 'test', ffprobeAvailable: true, rcloneAvailable: false, mppAvailable: true, rgaAvailable: true, encoders: [], decoders: [], filters: [], devices: {}, error: null, transcodeSlot: 0, uploadSlot: 0, uploadQueued: 0 } }),
  browse: vi.fn(), scan: vi.fn(), createTask: vi.fn(),
} }))

describe('new task wizard', () => {
  beforeEach(() => setActivePinia(createPinia()))

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
  })
})

