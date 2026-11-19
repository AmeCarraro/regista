import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { cacheState, searchCached } from './localCatalog.ts'

beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('window', { Regista: {} }) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

test('search uses the native saved catalog with pagination and releases the response token', async () => {
  const search = vi.fn()
  const cancel = vi.fn()
  window.Regista = { searchCachedCatalog: search, cancelCatalog: cancel,
    catalogResponse: () => JSON.stringify({ photos: [], total: 140, offset: 60, limit: 60 }) } as unknown as typeof window.Regista
  expect(await searchCached('due gatti', 60)).toEqual({ photos: [], total: 140, offset: 60, limit: 60 })
  expect(search).toHaveBeenCalledWith('due gatti', 60, expect.any(String))
  expect(cancel).toHaveBeenCalledWith(search.mock.calls[0][2])
})

test('aborted searches are canceled before an older result can replace the current one', async () => {
  const cancel = vi.fn()
  const response = vi.fn(() => '')
  window.Regista = { searchCachedCatalog: vi.fn(), cancelCatalog: cancel, catalogResponse: response } as unknown as typeof window.Regista
  const controller = new AbortController()
  const pending = searchCached('gatti', 0, controller.signal)
  const assertion = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  await assertion
  await vi.advanceTimersByTimeAsync(1000)
  expect(response).toHaveBeenCalledTimes(1)
  expect(cancel).toHaveBeenCalledTimes(1)
})

test('a missing app bridge is reported without contacting the PC', async () => {
  expect(cacheState().ready).toBe(false)
  await expect(searchCached('gatti', 0)).rejects.toThrow('Aggiorna l’app')
})

test('a failed local search keeps the native error visible', async () => {
  window.Regista = { searchCachedCatalog: vi.fn(), catalogResponse: () => '{"error":"Sincronizza il catalogo dal PC"}' } as unknown as typeof window.Regista
  await expect(searchCached('gatti', 0)).rejects.toThrow('Sincronizza il catalogo dal PC')
})

test('a stalled bridge is bounded and its pending token is removed', async () => {
  const cancel = vi.fn()
  window.Regista = { searchCachedCatalog: vi.fn(), cancelCatalog: cancel, catalogResponse: () => '' } as unknown as typeof window.Regista
  const pending = searchCached('gatti', 0)
  const assertion = expect(pending).rejects.toThrow('ricerca locale non risponde')
  await vi.advanceTimersByTimeAsync(15_100)
  await assertion
  expect(cancel).toHaveBeenCalledTimes(1)
})
