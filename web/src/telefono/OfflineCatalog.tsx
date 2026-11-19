import { useEffect, useState } from 'react'
import { cacheState, searchCached } from './localCatalog.ts'
import type { CachedPhoto, CachedResult } from './localCatalog.ts'

function Preview({ id, name, full = false }: { id: string; name: string; full?: boolean }) {
  const [failed, setFailed] = useState(false)
  return failed ? <span className="saved-placeholder">Anteprima non disponibile offline</span>
    : <img loading="lazy" src={`/catalog-media/${id}/${full ? 'full' : 'thumb'}`} alt={name} onError={() => setFailed(true)} />
}

export default function OfflineCatalog({ visible }: { visible: boolean }) {
  const [state, setState] = useState(cacheState)
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [result, setResult] = useState<CachedResult | null>(null)
  const [resultAt, setResultAt] = useState(0)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<CachedPhoto | null>(null)
  const [selectedAt, setSelectedAt] = useState(0)
  const [full, setFull] = useState(false)
  useEffect(() => {
    if (!visible) return
    const timer = setInterval(() => setState(cacheState()), 2000)
    return () => clearInterval(timer)
  }, [visible])
  useEffect(() => {
    if (!visible || !state.ready) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      setBusy(true)
      void searchCached(query, offset, controller.signal).then(found => {
        if (!controller.signal.aborted) { setResult(found); setResultAt(state.at); setProblem(''); setBusy(false) }
      }, error => {
        if (!controller.signal.aborted) { setProblem(error.message); setBusy(false) }
      })
    }, 180)
    return () => { clearTimeout(timer); controller.abort() }
  }, [visible, query, offset, state.ready, state.at])
  const shown = resultAt === state.at ? result : null
  if (!visible) return null
  return <section className="saved-catalog" aria-label="Catalogo salvato sul telefono">
    <h2>Il catalogo sul telefono</h2>
    <p>Tag, descrizioni e date arrivano dal PC. Qui cerchi senza AI e anche a PC spento.</p>
    <button disabled={state.syncing} onClick={() => { window.Regista?.syncCatalog?.(); setState(cacheState()) }}>
      {state.syncing ? 'Sincronizzazione in corso…' : 'Aggiorna il catalogo dal PC'}
    </button>
    {state.error && <p role="status">{state.error} La copia precedente resta disponibile.</p>}
    {state.ready ? <>
      <p>{state.count} foto · Aggiornato {new Date(state.at).toLocaleString('it-IT')}</p>
      <label>Cerca parole, tag, date o luoghi
        <input value={query} maxLength={1000} placeholder="cani, oppure due gatti" onChange={event => { setQuery(event.target.value); setOffset(0) }} />
      </label>
      {problem && <p role="alert">{problem}</p>}
      <p role="status">{busy ? 'Cerco…' : `${shown?.total ?? 0} risultati`}</p>
      <div className="saved-grid">{shown?.photos.map(photo => <button className="saved-photo" key={photo.id}
        onClick={() => { setSelected(photo); setSelectedAt(state.at); setFull(false) }}>
        <Preview id={photo.id} name={photo.name} />
        <b>{photo.name}</b><span>{photo.metadata.date || 'Data non disponibile'}</span>
        <span>{photo.tags.slice(0, 5).map(tag => tag.tag).join(' · ') || 'In attesa dei tag del PC'}</span>
      </button>)}</div>
      {shown && shown.total > 60 && <div className="saved-pages">
        <button disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 60))}>Precedenti</button>
        <button disabled={offset + 60 >= shown.total || busy} onClick={() => setOffset(offset + 60)}>Successive</button>
      </div>}
    </> : <p>Collega il PC per ricevere la prima copia del catalogo. Musica e video del telefono sono disponibili anche senza collegamento.</p>}
    {state.ready && selected && selectedAt === state.at && <div className="saved-details" role="dialog" aria-modal="true" aria-label={selected.name}>
      <button autoFocus onClick={() => setSelected(null)}>Chiudi foto</button>
      <h2>{selected.name}</h2>
      <Preview key={`${selected.id}-${full}`} id={selected.id} name={selected.name} full={full} />
      {!full && <button onClick={() => setFull(true)}>Apri immagine completa</button>}
      <p>L’immagine si apre dalla copia sul telefono, quando presente, oppure dal PC collegato.</p>
      <p>{selected.description}</p>
      <p>{selected.tags.map(tag => tag.tag).join(' · ')}</p>
      <p>{selected.metadata.date} {selected.metadata.place}</p>
    </div>}
  </section>
}
