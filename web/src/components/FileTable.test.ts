import { shallowRef } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CompanionFile, TaskFile } from '../types'
import FileTable from './FileTable.vue'

const measureElement = vi.hoisted(() => vi.fn())

vi.mock('@tanstack/vue-virtual', () => ({
  useVirtualizer: () => shallowRef({
    getTotalSize: () => 94,
    getVirtualItems: () => [
      { index: 0, key: 'file-1', start: 0, size: 47, end: 47, lane: 0 },
      { index: 1, key: 'companion-1', start: 47, size: 47, end: 94, lane: 0 },
    ],
    measureElement,
  }),
}))

const video: TaskFile = {
  id: 'file-1', taskId: 'task-1', relativePath: 'movie.mp4', stage: 'completed', attempt: 1,
  sourceSize: 1024, finalOutputPath: null, artifactSize: 512, progress: null,
  parameterDecision: { source: { bitrateKbps: 228 }, requested: { bitrateKbps: 2000 }, effective: { bitrateKbps: 228 }, reasons: [], ffmpegArgv: ['ffmpeg', '-i', 'movie.mp4'] },
  ffmpegOutput: 'frame=120 fps=30.0 bitrate=1800k',
  lastError: null, lastExitCode: 0, version: 1, startedAt: null, finishedAt: null, updatedAt: '',
}

const companion: CompanionFile = {
  id: 'companion-1', taskId: 'task-1', relativePath: 'cover.jpg', category: 'other', stage: 'completed',
  attempt: 1, sourceSize: 2048, finalOutputPath: null, lastError: null, version: 1, updatedAt: '',
}

describe('file table details', () => {
  beforeEach(() => measureElement.mockClear())

  it('keeps the headers visible and opens file details in a modal', async () => {
    const wrapper = mount(FileTable, { props: { files: [video], companions: [companion] } })
    await flushPromises()

    expect(wrapper.find('.file-table-head').text()).toContain('文件类型状态尝试')
    expect(measureElement).toHaveBeenCalledTimes(2)

    await wrapper.find('.file-row').trigger('click')
    expect(document.body.textContent).toContain('文件详情')
    expect(document.body.textContent).toContain('源参数 Source')
    expect(document.body.textContent).toContain('实际参数 Effective')
    expect(document.body.textContent).toContain('实际 FFmpeg 参数')
    expect(document.body.textContent).toContain('ffmpeg -i movie.mp4')
    expect(document.body.textContent).toContain('实际 FFmpeg 输出')
    expect(document.body.textContent).toContain('frame=120 fps=30.0 bitrate=1800k')
    expect(document.querySelector('.argv details')).toBeNull()
    expect(document.querySelector('.file-detail-scroll .dialog-heading')).toBeNull()
  })
})
