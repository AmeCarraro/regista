import { useEffect, useState } from 'react'
import { cacheState, searchCached } from './localCatalog.ts'
import type { CachedPhoto, CachedResult } from './localCatalog.ts'
import { Cross, Picture, Refresh, Search } from '../icons.tsx'

function Preview({ id, name, full = false }: { id: string; name: string; full?: boolean }) {
  const [failed, setFailed] = useState(false)
  return failed ? <span className="saved-placeholder"><Picture />Anteprima non disponibile offline</span>
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
  const [kind, setKind] = useState('all')
  const [album, setAlbum] = useState('')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [hidden, setHidden] = useState(false)
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
      void searchCached(query, offset, controller.signal, { kind, album, since, until, include_hidden: hidden }).then(found => {
        if (!controller.signal.aborted) { setResult(found); setResultAt(state.at); setProblem(''); setBusy(false) }
      }, error => {
        if (!controller.signal.aborted) { setProblem(error.message); setBusy(false) }
      })
    }, 180)
    return () => { clearTimeout(timer); controller.abort() }
  }, [visible, query, offset, state.ready, state.at, kind, album, since, until, hidden])
  const shown = resultAt === state.at ? result : null
  if (!visible) return null
  return <section className="saved-catalog" aria-label="Catalogo salvato sul telefono">
    <div className="phone-section-heading"><h2>Il tuo catalogo</h2>
      <button className="phone-icon" disabled={state.syncing} aria-label={state.syncing ? 'Sincronizzazione in corso' : 'Aggiorna il catalogo dal PC'}
        onClick={() => { window.Regista?.syncCatalog?.(); setState(cacheState()) }}><Refresh /></button>
    </div>
    {state.error && <p className="phone-feedback" role="status">{state.error} La copia precedente resta disponibile.</p>}
    {state.ready ? <>
      <p className="phone-caption">{state.count} foto e video · Aggiornato {new Date(state.at).toLocaleString('it-IT')}</p>
      <label className="ask saved-search"><Search />
        <input aria-label="Cerca parole, tag, date o luoghi" value={query} maxLength={1000} placeholder="Cani, due gatti, Giappone…" enterKeyHint="search" onChange={event => { setQuery(event.target.value); setOffset(0) }} />
      </label>
      <details className="saved-filters"><summary>Album, tipo e date</summary><div className="saved-filter-fields">
        <label>Tipo<select value={kind} onChange={event => { setKind(event.target.value); setOffset(0) }}><option value="all">Foto e video</option><option value="image">Foto</option><option value="video">Video</option></select></label>
        <label>Album<select value={album} onChange={event => { setAlbum(event.target.value); setOffset(0) }}><option value="">Tutti gli album</option>{state.albums?.map(item => <option key={item.id} value={item.id}>{item.name}{item.hidden ? ' · nascosto' : ''}</option>)}</select></label>
        <label>Dal<input type="date" value={since} onChange={event => { setSince(event.target.value); setOffset(0) }} /></label>
        <label>Al<input type="date" value={until} onChange={event => { setUntil(event.target.value); setOffset(0) }} /></label>
      </div><label className="phone-toggle"><span>Mostra anche gli elementi nascosti</span><input type="checkbox" checked={hidden} onChange={event => { setHidden(event.target.checked); setOffset(0) }} /></label></details>
      {problem && <p className="phone-feedback" role="alert">{problem}</p>}
      <p className="phone-caption saved-result-count" role="status">{busy ? 'Cerco…' : `${shown?.total ?? 0} risultati`}</p>
      {!busy && shown?.total === 0 && <p className="phone-empty">Nessuna foto trovata. Prova un altro tag o un luogo.</p>}
      <div className="saved-grid">{shown?.photos.map(photo => <button className="saved-photo" key={photo.id}
        onClick={() => { setSelected(photo); setSelectedAt(state.at); setFull(false) }}>
        <Preview id={photo.id} name={photo.name} />
        <b>{photo.kind === 'video' ? '▶ ' : ''}{photo.name}</b><span>{photo.metadata.date || 'Data non disponibile'}</span>
        <span>{photo.tags.slice(0, 5).map(tag => tag.tag).join(' · ') || 'In attesa dei tag del PC'}</span>
      </button>)}</div>
      {shown && shown.total > 60 && <div className="saved-pages">
        <button className="phone-action" disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 60))}>Precedenti</button>
        <button className="phone-action" disabled={offset + 60 >= shown.total || busy} onClick={() => setOffset(offset + 60)}>Successive</button>
      </div>}
    </> : <div className="phone-empty"><span className="phone-empty-icon"><Picture /></span><h3>I tuoi ricordi, anche offline</h3>
      <p>Collega il PC dalla scheda Computer e aggiorna il catalogo. Potrai cercare tag, luoghi e descrizioni anche a computer spento.</p>
      <p className="phone-caption">Musica e video sono già disponibili sul telefono.</p>
    </div>}
    {state.ready && selected && selectedAt === state.at && <div className="saved-details" role="dialog" aria-modal="true" aria-label={selected.name}>
      <div className="phone-section-heading"><h2>{selected.name}</h2><button className="phone-icon" autoFocus aria-label="Chiudi foto" onClick={() => setSelected(null)}><Cross /></button></div>
      <Preview key={`${selected.id}-${full}`} id={selected.id} name={selected.name} full={full} />
      {!full && selected.kind !== 'video' && <button className="phone-action" onClick={() => setFull(true)}>Apri immagine completa</button>}
      {selected.kind === 'video' && <button className="phone-action" onClick={() => {
        const response = window.Regista?.openCachedMedia?.(selected.id)
        if (response) { const value = JSON.parse(response); if (value.error) setProblem(value.error) }
      }}>Riproduci il video del telefono</button>}
      <p className="phone-caption">L’immagine si apre dalla copia sul telefono, quando presente, oppure dal PC collegato.</p>
      <p>{selected.description}</p>
      <div className="saved-tags">{selected.tags.map(tag => <span key={`${tag.source}:${tag.tag}`}>{tag.tag}</span>)}</div>
      <p>{selected.metadata.date} {selected.metadata.place}</p>
      {selected.metadata.source_folder && <p className="phone-caption">Cartella originale: {selected.metadata.source_folder}</p>}
    </div>}
  </section>
}
