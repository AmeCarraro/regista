import './bridge.ts'

export type CacheState = { ready: boolean; syncing: boolean; count: number; at: number; error: string; albums?: { id: string; name: string; hidden: boolean }[] }
export type CachedPhoto = { id: string; name: string; description: string; stage: string;
  kind?: string; metadata: { date?: string; place?: string; source_folder?: string; source_folders?: string[] }; tags: { tag: string; source: string }[] }
export type CachedResult = { photos: CachedPhoto[]; total: number; offset: number; limit: number }

export function cacheState(): CacheState {
  try {
    const raw = window.Regista?.cachedCatalog?.()
    if (raw) return JSON.parse(raw) as CacheState
  } catch { /* Older app or cache temporarily unavailable. */ }
  return { ready: false, syncing: false, count: 0, at: 0, error: '' }
}

let serial = 0
export function searchCached(query: string, offset: number, signal?: AbortSignal, filters?: Record<string, unknown>): Promise<CachedResult> {
  return new Promise((resolve, reject) => {
    const native = window.Regista
    if (!native?.searchCachedCatalog || !native.catalogResponse) { reject(new Error('Aggiorna l’app per cercare nel catalogo salvato.')); return }
    const token = `${Date.now().toString(36)}${(++serial).toString(36)}`
    const deadline = Date.now() + 15_000
    let timer: ReturnType<typeof setTimeout>
    const cancel = () => { native.cancelCatalog?.(token); clearTimeout(timer); signal?.removeEventListener('abort', abort) }
    const abort = () => { cancel(); reject(new DOMException('Ricerca annullata', 'AbortError')) }
    if (signal?.aborted) { abort(); return }
    signal?.addEventListener('abort', abort, { once: true })
    if (filters && native.searchCachedCatalogWithFilters) native.searchCachedCatalogWithFilters(query, offset, JSON.stringify(filters), token)
    else native.searchCachedCatalog(query, offset, token)
    const poll = () => {
      const raw = native.catalogResponse!(token)
      if (raw) {
        cancel()
        try {
          const result = JSON.parse(raw)
          if (result.error) reject(new Error(result.error))
          else resolve(result as CachedResult)
        } catch { reject(new Error('Catalogo salvato non leggibile.')) }
      } else if (Date.now() > deadline) { cancel(); reject(new Error('La ricerca locale non risponde. Riprova.')) }
      else timer = setTimeout(poll, 50)
    }
    poll()
  })
}
