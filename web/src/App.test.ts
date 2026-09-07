import { shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import { useTasksStore } from './stores/tasks'

describe('application status bar', () => {
  beforeEach(() => setActivePinia(createPinia()))

  function mountApp(remotes: string[]) {
    const store = useTasksStore()
    store.remotes = remotes
    vi.spyOn(store, 'loadSnapshot').mockResolvedValue()
    vi.spyOn(store, 'loadRemotes').mockResolvedValue()
    vi.spyOn(store, 'connectEvents').mockImplementation(() => undefined)
    return shallowMount(App, {
      global: {
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
          RouterView: true,
        },
      },
    })
  }

  it('shows configured Rclone remotes in a status popover', () => {
    const wrapper = mountApp(['nas', 'webdav', 'archive'])
    const status = wrapper.get('details.status-remotes')

    expect(status.get('summary').text()).toBe('Rclone · 3 Remotes')
    expect(status.findAll('.remote-status-details p').map((item) => item.text())).toEqual([
      'nas:',
      'webdav:',
      'archive:',
    ])
  })

  it('shows an empty-state message when no remote is configured', () => {
    const wrapper = mountApp([])
    const status = wrapper.get('details.status-remotes')

    expect(status.get('summary').text()).toBe('Rclone · 0 Remotes')
    expect(status.get('.remote-status-details').text()).toBe('未配置 Rclone Remote')
  })
})
