import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './catalog.css'
import { catalogRequest } from './catalogApi.ts'
import type { CatalogRequest } from './catalogApi.ts'
import CatalogBulk from './CatalogBulk.tsx'
import ImportArchives from './ImportArchives.tsx'
type Status = {
  discovered: number; analyzed: number; pending: number; failed: number; missing: number; coverage: number; excluded: number
  scanning: boolean; scan_error: string; mode: string; current: string; problem: string; waiting_reason: string; version: string
  computer: boolean; roots: { id: string; label: string; path?: string }[]
  errors: { asset_id: string; error: string; attempts: number }[]
  imports: { state: string; total: number; copied: number; duplicates: number; error: string }[]
  classified?: number; to_catalog?: number; awaiting_transfer?: number
  backup?: { count: number; bytes: number; errors: number }
  incoming?: { sha256: string; name: string; copies: number; state: string; error: string }[]
}
type Photo = {
  id: string; name: string; folder: string; description: string; day: string; excluded_reason: string; kind?: string
  metadata: { date: string; precision: string; date_source: string; place: string; place_source: string; path_hint: string; conflicts: string[] }
  tags: { tag: string; source: string }[]; reasons: string[]
  annotation: { model: string; digest: string; prompt_version: string; schema_version: string } | null
  catalog_state?: string; processing?: { state: string; error: string }; backup_available?: boolean
}
type Result = { photos: Photo[]; total: number; coverage: Status; plan: Record<string, unknown>; notice: string }

export default function Catalog({ visible = true, request = catalogRequest, mediaUrl }: {
  visible?: boolean; request?: CatalogRequest; mediaUrl?: (id: string, full: boolean) => Promise<string>
}) {
  const [status, setStatus] = useState<Status | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [query, setQuery] = useState('')
  const [natural, setNatural] = useState(false)
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [place, setPlace] = useState('')
  const [folder, setFolder] = useState('')
  const [tag, setTag] = useState('')
  const [stage, setStage] = useState('all')
  const [kind, setKind] = useState('all')
  const [album, setAlbum] = useState('')
  const [albums, setAlbums] = useState<{ id: string; name: string; hidden: boolean; count: number }[]>([])
  const [includeHidden, setIncludeHidden] = useState(false)
  const [operator, setOperator] = useState('and')
  const [exclude, setExclude] = useState('')
  const [root, setRoot] = useState('')
  const [newRoot, setNewRoot] = useState('')
  const [problem, setProblem] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [original, setOriginal] = useState<{ url: string; video: boolean } | null>(null)
  const anchor = useRef('')

  const refresh = useCallback(async () => setStatus(await request<Status>('/api/catalog/status')), [request])
  useEffect(() => {
    if (!visible) return
    let active = true
    const read = () => request<Status>('/api/catalog/status').then(value => { if (active) setStatus(value) }, error => {
      if (active) { setStatus(null); setProblem(String(error.message)) }
    })
    void read()
    const timer = setInterval(() => void read(), 3000)
    return () => { active = false; clearInterval(timer) }
  }, [visible, request])

  async function perform(work: () => Promise<void>) {
    setBusy(true); setProblem(''); setNote('')
    try { await work() } catch (error) { setProblem(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }

  const find = useCallback(async (offset = 0, savedPlan?: Record<string, unknown>) => {
    const plan = savedPlan ?? (natural && query.trim()
      ? await request<Record<string, unknown>>('/api/catalog/plan', { query })
      : { terms: query.trim() ? query.trim().split(/\s+/) : [], operator, exclude: exclude.split(',').map(x => x.trim()).filter(Boolean) })
    const found = await request<Result>('/api/catalog/search', { ...plan, ...(natural && query.trim() ? { exclude: [...new Set([...(Array.isArray(plan.exclude) ? plan.exclude : []), ...exclude.split(',').map(x => x.trim()).filter(Boolean)])] } : {}), ...(since ? { since } : {}), ...(until ? { until } : {}),
      ...(place ? { place } : {}), ...(folder ? { folder } : {}), ...(tag ? { tag } : {}), stage, kind, album, include_hidden: includeHidden, root_id: root, limit: 60, offset })
    setResult(found); setSelected([])
  }, [request, natural, query, operator, exclude, since, until, place, folder, tag, stage, kind, album, includeHidden, root])

  const refreshAlbums = useCallback(async () => setAlbums((await request<{ albums: typeof albums }>('/api/catalog/albums')).albums), [request])
  useEffect(() => {
    if (!visible) return
    let active = true
    void request<{ albums: typeof albums }>('/api/catalog/albums').then(value => { if (active) setAlbums(value.albums) }, () => {})
    return () => { active = false }
  }, [visible, request])

  useEffect(() => {
    if (!visible) return
    void request<Result>('/api/catalog/search', {}).then(setResult, () => {})
  }, [visible, request])

  const control = (command: string) => perform(async () => {
    await request('/api/catalog/control', { command, ids: selected }); await refresh()
    if (command === 'reanalyze') setNote(`${selected.length} foto messe in coda. Premi Avvia per analizzarle.`)
  })
  const submit = (event: FormEvent) => { event.preventDefault(); void perform(() => find()) }

  if (!visible) return null
  return <section className="catalog-page" aria-label="Catalogo foto e video">
    <header className="catalog-header"><div><h1>Foto e video</h1><p>Raccogli i ricordi, organizza i viaggi. Avvia l’analisi quando vuoi tu.</p></div></header>
    {problem && <p role="alert" className="catalog-alert">{problem}</p>}
    {note && <p role="status">{note}</p>}
    {!status && <p>Catalogo del PC non disponibile. Il computer deve essere acceso e collegato.</p>}
    {status && <>
      <div className="catalog-counts" aria-live="polite">
        <span><b>{status.discovered}</b> foto e video diversi</span><span><b>{status.classified ?? status.analyzed}</b> classificati</span>
        <span><b>{status.to_catalog ?? status.discovered - status.analyzed}</b> da catalogare</span>
        <span><b>{status.pending}</b> in attesa</span><span><b>{status.failed}</b> errori</span><span><b>{status.excluded}</b> esclusi dall’analisi</span><span><b>{status.missing}</b> file mancanti</span>
      </div>
      <progress max={100} value={status.coverage} aria-label="Copertura del catalogo" /><p className="catalog-muted">Copertura {status.coverage}% · {status.mode === 'paused' ? 'Analisi AI in pausa' : status.mode === 'idle' ? 'Solo quando inattivo' : 'Analisi avviata'}{status.scanning && ' · Scansione in corso'}{status.current && ' · Un file in analisi'}</p>
      {status.current && <img className="catalog-current" src={`/api/catalog/photos/${status.current}/thumb`} alt="Foto attualmente in analisi" />}
      {status.computer && <>
        <div className="catalog-toolbar">
          <button disabled={busy || status.scanning} onClick={() => void perform(async () => {
            const scanned = await request<{ changed: number; deferred: number }>('/api/catalog/scan', {}); await refresh(); await find()
            setNote(`Scansione completata: ${scanned.changed} file nuovi o aggiornati, ${scanned.deferred} ancora in scrittura.`)
          })}>Scansiona cartelle</button>
          <button disabled={busy} onClick={() => void control('start')}>Avvia / Riprendi tag</button>
          <button disabled={busy} onClick={() => void control('pause')}>Pausa</button>
          <button disabled={busy} onClick={() => void control('idle')}>Solo quando inattivo</button>
          <button disabled={busy || !status.failed} onClick={() => void control('retry')}>Riprova errori</button>
          <button disabled={busy || !selected.length} onClick={() => void control('reanalyze')}>Rianalizza selezione ({selected.length})</button>
          <button disabled={busy} onClick={() => void perform(async () => {
            const imported = await request<{ devices: number }>('/api/catalog/phone-import', {})
            setNote(`Importazione richiesta a ${imported.devices} telefoni. Apri Regista sul telefono; i tag restano in pausa.`); await refresh()
          })}>Importa foto e video dal telefono</button>
        </div>
        <details><summary>Cartelle autorizzate e modello</summary><ul>{status.roots.map(r => <li key={r.id}>{r.label}: {r.path}</li>)}</ul>
          <form onSubmit={event => { event.preventDefault(); void perform(async () => {
            await request('/api/catalog/roots', { path: newRoot }); setNewRoot(''); await refresh()
          }) }}><label>Cartella del PC<input value={newRoot} onChange={e => setNewRoot(e.target.value)} placeholder="C:\Foto" /></label><button disabled={busy || !newRoot}>Aggiungi cartella</button></form>
          <p className="catalog-muted">Modello e versione: {status.version}. Nessun modello viene scaricato automaticamente.</p>
        </details>
      </>}
      {status.computer && <ImportArchives request={request} />}
      {(status.problem || status.scan_error || status.waiting_reason) && <p role="status">{status.problem || status.scan_error || status.waiting_reason}</p>}
      {status.imports?.map((item, at) => <p key={at} role="status">Telefono: {item.state === 'requested' ? 'in attesa del telefono' : item.state === 'done' ? 'importazione completata' : 'copia in corso'} · {item.copied} copiate · {item.duplicates} già presenti · {item.total} totali {item.error}</p>)}
      {status.failed > 0 && status.computer && <details><summary>Errori di analisi</summary>{status.errors.map(error => <p key={error.asset_id}>{error.asset_id.slice(0, 8)}: {error.error} ({error.attempts} tentativi)</p>)}</details>}
      {status.computer && <>
        <details><summary>Da trasferire dal telefono ({status.awaiting_transfer ?? 0})</summary>
          <p>Le foto già ricevute vengono riconosciute dal contenuto e non sono richieste di nuovo. Per riprendere usa «Importa tutte le foto dal telefono».</p>
          {status.incoming?.map(item => <p key={item.sha256}>{item.name || item.sha256.slice(0, 12)}{item.copies > 1 && ` · ${item.copies} copie identiche`} · {item.error || 'In attesa dell’originale'}</p>)}
          {(status.awaiting_transfer ?? 0) > 20 && <p>Mostrate le prime 20 foto ancora da ricevere.</p>}
        </details>
        {status.backup && <details><summary>Backup originali ZIP ({status.backup.count})</summary>
          <p>{status.backup.count} originali conservati prima della classificazione · {(status.backup.bytes / 1024 ** 2).toFixed(1)} MB{status.backup.errors > 0 && ` · ${status.backup.errors} problemi da risolvere`}</p>
          <p>Le importazioni sono organizzate in «Da catalogare» e «Classificate». Puoi scaricare il backup originale dalla scheda della foto.</p>
        </details>}
      </>}
      <form className="catalog-search" onSubmit={submit}>
        <label>Cerca nelle descrizioni e nei tag<input value={query} onChange={e => setQuery(e.target.value)} placeholder={natural ? 'Cani in Giappone nel marzo 2025' : 'cane nero'} /></label>
        <label className="catalog-check"><input type="checkbox" checked={natural} onChange={e => setNatural(e.target.checked)} />Interpreta la richiesta con Qwen (solo testo)</label>
        <div className="catalog-filters">
          <label>Stato<select value={stage} onChange={e => setStage(e.target.value)}><option value="all">Tutte le foto</option><option value="classified">Classificate</option><option value="to_catalog">Da catalogare</option><option value="needs_review">Da catalogare con errore</option></select></label>
          <label>Tipo<select value={kind} onChange={e => setKind(e.target.value)}><option value="all">Foto e video</option><option value="image">Foto</option><option value="video">Video</option></select></label>
          <label>Album<select value={album} onChange={e => setAlbum(e.target.value)}><option value="">Tutti gli album</option>{albums.map(item => <option key={item.id} value={item.id}>{item.name} ({item.count}){item.hidden ? ' · nascosto' : ''}</option>)}</select></label>
          <label>Dal<input type="date" value={since} onChange={e => setSince(e.target.value)} /></label>
          <label>Al<input type="date" value={until} onChange={e => setUntil(e.target.value)} /></label>
          <label>Luogo da GPS<input value={place} onChange={e => setPlace(e.target.value)} placeholder="Giappone" /></label>
          <label>Indizio cartella<input value={folder} onChange={e => setFolder(e.target.value)} /></label>
          <label>Tag<input value={tag} onChange={e => setTag(e.target.value)} /></label>
          <label>Termini<select disabled={natural} value={operator} onChange={e => setOperator(e.target.value)}><option value="and">Tutti (AND)</option><option value="or">Almeno uno (OR)</option></select></label>
          <label>Escludi (separati da virgole)<input value={exclude} onChange={e => setExclude(e.target.value)} /></label>
          <label>Radice<select value={root} onChange={e => setRoot(e.target.value)}><option value="">Tutte le cartelle</option>{status.roots.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</select></label>
        </div><label className="catalog-check"><input type="checkbox" checked={includeHidden} onChange={e => setIncludeHidden(e.target.checked)} />Mostra anche gli elementi nascosti</label><button disabled={busy}>{busy ? 'Attendi…' : 'Cerca'}</button>
      </form>
      {album && status.computer && <div className="catalog-toolbar"><button disabled={busy} onClick={() => void perform(async () => {
        await request(`/api/catalog/albums/${album}/visibility`, { hidden: !albums.find(item => item.id === album)?.hidden }); await refreshAlbums(); await find()
      })}>{albums.find(item => item.id === album)?.hidden ? 'Mostra questo album nella vista generale' : 'Nascondi questo album dalla vista generale'}</button><p className="catalog-muted">L’album rimane consultabile qui, con foto e video insieme.</p></div>}
    </>}
    {result && <><p aria-live="polite">{result.total} risultati · {result.coverage.coverage}% del catalogo analizzato</p>
      {status?.computer && <CatalogBulk selected={selected} plan={result.plan} total={result.total} request={request} onChanged={async () => { await find(0, result.plan); await refreshAlbums() }} />}
      {result.total === 0 && <p>Nessuna corrispondenza nei dati disponibili. Le foto in attesa potrebbero non avere ancora tag.</p>}
      <div className="catalog-grid">{result.photos.map(photo => <article key={photo.id}>
        <CatalogThumb photo={photo} mediaUrl={mediaUrl} onOpen={() => void perform(async () => setOriginal({ url: mediaUrl ? await mediaUrl(photo.id, true) : `/api/catalog/photos/${photo.id}/full`, video: photo.kind === 'video' }))} />
        <div className="catalog-card-body">
          {status?.computer && <label className="catalog-check"><input type="checkbox" checked={selected.includes(photo.id)} onChange={() => {}} onClick={event => {
            const checked = event.currentTarget.checked
            const first = result.photos.findIndex(item => item.id === anchor.current), last = result.photos.findIndex(item => item.id === photo.id)
            const ids = event.shiftKey && first >= 0 ? result.photos.slice(Math.min(first, last), Math.max(first, last) + 1).map(item => item.id) : [photo.id]
            setSelected(before => checked ? [...new Set([...before, ...ids])] : before.filter(id => !ids.includes(id)))
            anchor.current = photo.id
          }} />Seleziona</label>}
          <b>{photo.kind === 'video' && '▶ '}{photo.name}</b><p>{photo.excluded_reason || photo.description || 'In attesa di analisi'}</p>
          <p className="catalog-muted">{photo.catalog_state === 'classified' ? 'Classificata' : photo.catalog_state === 'needs_review' ? 'Da catalogare · da rivedere' : 'Da catalogare'}</p>
          {photo.processing?.error && <p role="status" className="catalog-alert">{photo.processing.error}</p>}
          {status?.computer && photo.backup_available && <p><a href={`/api/catalog/photos/${photo.id}/backup`} download>Scarica originale in ZIP</a></p>}
          <div className="catalog-tags">{photo.tags.map(item => <span key={item.tag} title={`Fonte: ${item.source}`}>{item.tag}{status?.computer && <button aria-label={`Escludi tag ${item.tag}`} onClick={() => void perform(async () => {
            await request(`/api/catalog/photos/${photo.id}/tags`, { tag: item.tag, included: false }, 'PUT'); await find(0, result.plan)
          })}>×</button>}</span>)}</div>
          {status?.computer && <form onSubmit={event => { event.preventDefault(); const form = event.currentTarget; const term = String(new FormData(form).get('tag') || ''); void perform(async () => {
            await request(`/api/catalog/photos/${photo.id}/tags`, { tag: term, included: true }, 'PUT'); form.reset(); await find(0, result.plan)
          }) }}><input name="tag" aria-label={`Correggi tag di ${photo.name}`} placeholder="Aggiungi o ripristina tag" maxLength={100} required /><button>Salva</button></form>}
          <p className="catalog-muted">{photo.day || 'Data sconosciuta'}{photo.day && ` · fonte ${photo.metadata.date_source}, precisione ${photo.metadata.precision}`}</p>
          {photo.metadata.place && <p className="catalog-muted">{photo.metadata.place} · {photo.metadata.place_source}</p>}
          {photo.folder && <p className="catalog-muted">Cartella (indizio): {photo.folder}</p>}
          {photo.metadata.conflicts?.map(conflict => <p key={conflict}>{conflict}</p>)}
          {photo.reasons.map(reason => <small key={reason}>{reason}<br /></small>)}
          {photo.annotation && <details><summary>Provenienza analisi</summary><small>{photo.annotation.model}<br />Digest {photo.annotation.digest}<br />Prompt {photo.annotation.prompt_version} · Schema {photo.annotation.schema_version}</small></details>}
        </div>
      </article>)}</div>
      <div className="catalog-toolbar"><button disabled={busy || Number(result.plan.offset) === 0} onClick={() => void perform(() => find(Math.max(0, Number(result.plan.offset) - 60), result.plan))}>Precedenti</button>
        <button disabled={busy || Number(result.plan.offset) + result.photos.length >= result.total} onClick={() => void perform(() => find(Number(result.plan.offset) + 60, result.plan))}>Successive</button></div><p className="catalog-muted">{result.notice}</p>
    </>}
    {original && <div className="catalog-lightbox" role="dialog" aria-modal="true" aria-label="Originale"><button onClick={() => { if (original.url.startsWith('blob:')) URL.revokeObjectURL(original.url); setOriginal(null) }}>Chiudi</button>{original.video ? <video src={original.url} controls autoPlay playsInline /> : <img src={original.url} alt="Foto originale richiesta" />}</div>}
  </section>
}

function CatalogThumb({ photo, mediaUrl, onOpen }: { photo: Photo; mediaUrl?: (id: string, full: boolean) => Promise<string>; onOpen: () => void }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!mediaUrl) return
    let active = true
    let loaded = ''
    void mediaUrl(photo.id, false).then(value => { loaded = value; if (active) setUrl(value); else if (value.startsWith('blob:')) URL.revokeObjectURL(value) }, () => {})
    return () => { active = false; if (loaded.startsWith('blob:')) URL.revokeObjectURL(loaded) }
  }, [photo.id, mediaUrl])
  return <button className="catalog-image" onClick={onOpen} aria-label={`Apri originale di ${photo.name}`}><img loading="lazy" src={mediaUrl ? url || undefined : `/api/catalog/photos/${photo.id}/thumb`} alt={photo.description || photo.name} /></button>
}
