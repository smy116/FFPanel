import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, http } from './api'

describe('complete file listings', () => {
  afterEach(() => vi.restoreAllMocks())

  it.each(['files', 'companions'] as const)('loads %s beyond the first 500 rows', async (kind) => {
    const first = Array.from({ length: 500 }, (_, id) => ({ id: String(id) }))
    const get = vi.spyOn(http, 'get')
      .mockResolvedValueOnce({ data: { items: first, total: 501 } })
      .mockResolvedValueOnce({ data: { items: [{ id: '500' }], total: 501 } })
    const items = await api[kind]('task-1')
    expect(items).toHaveLength(501)
    expect(items[500].id).toBe('500')
    expect(get).toHaveBeenNthCalledWith(2, `/tasks/task-1/${kind}`, { params: { offset: 500, limit: 500 } })
  })

  it('reports a later page failure instead of returning a truncated list', async () => {
    vi.spyOn(http, 'get').mockResolvedValueOnce({ data: { items: [{ id: '1' }], total: 2 } })
      .mockRejectedValueOnce(new Error('connection lost'))
    await expect(api.files('task-1')).rejects.toThrow('connection lost')
  })

  it('finishes empty lists without requesting more pages', async () => {
    const get = vi.spyOn(http, 'get').mockResolvedValueOnce({ data: { items: [], total: 0 } })
    expect(await api.files('task-1')).toEqual([])
    expect(get).toHaveBeenCalledTimes(1)
  })
})
