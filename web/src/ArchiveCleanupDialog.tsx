import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { CatalogRequest } from './catalogApi.ts'

type Device = { id: string; name: string }
type Filter = { source: string; kind: string; since: string; until: string }
type CleanupFile = { media: string; name: string; folder: string; kind: string; day: string; sha256: string; date_source: string }
type Cleanup = { id: string; state: string; updated: number; count: number; images: number; videos: number;
  folder_files: number; selected: number; removed: number; selected_remaining: number; error: string; files: CleanupFile[]; offset: number; limit: number;
  scanned: number; scan_total: number; parts: number; review: number;
  policy: { source: string; kind: string; since: string | null; until: string | null } }
type Selection = { key: string; all: boolean; exceptions: Set<string> }

const anyFile: Filter = { source: 'all', kind: 'all', since: '', until: '' }
const whatsAppPhotos: Filter = { source: 'whatsapp', kind: 'image', since: '', until: '2024-12-31' }
const states: Record<string, string> = {
  verifying: 'Preparo il confronto con le importazioni completate…',
  finding: 'Verifica degli originali sul telefono',
  matched: 'Anteprima pronta',
  approved: 'Apri Regista sul telefono e conferma la rimozione anche lì.',
  reviewed: 'Revisione del lotto conclusa',
  finished: 'Rimozione conclusa',
  cancelled: 'Rimozione interrotta',
  error: 'Verifica non riuscita',
}
const activeStates = ['verifying', 'finding', 'matched', 'approved', 'reviewed']
const dateSources: Record<string, string> = { file: 'Data del file', whatsapp_name: 'Data nel nome WhatsApp', capture: 'Data di scatto' }
const origins: Record<string, string> = { all: 'Tutte le provenienze', whatsapp: 'WhatsApp', telegram: 'Telegram', normal: 'Fotocamera e altre cartelle' }
const kinds: Record<string, string> = { all: 'Foto e video', image: 'Solo foto', video: 'Solo video' }
const formatDate = (day: string) => day.split('-').reverse().join('/')
const number = new Intl.NumberFormat('it-IT')
const emptySelection = new Set<string>()

export default function ArchiveCleanupDialog({ request, archive, onClose }: {
  request: CatalogRequest; archive: { id: string; device: string } | null; onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const batch = archive?.id
  const defaultDevice = archive?.device
  const [devices, setDevices] = useState<Device[]>([])
  const [device, setDevice] = useState(defaultDevice || '')
  const [filter, setFilter] = useState(anyFile)
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<Cleanup | null>(null)
  const [offset, setOffset] = useState(0)
  const [selection, setSelection] = useState<Selection>({ key: '', all: false, exceptions: emptySelection })
  const [busy, setBusy] = useState('')
  const [problem, setProblem] = useState('')
  const [loadingPrevious, setLoadingPrevious] = useState(true)

  useEffect(() => { dialog.current?.showModal() }, [])
  useEffect(() => {
    let active = true
    const calls = [
      request<{ devices: Device[] }>('/api/phone').then(result => {
        if (!active) return
        setDevices(result.devices)
        if (!defaultDevice && result.devices.length === 1) setDevice(result.devices[0].id)
      }),
      (batch ? request<{ cleanup: { id: string } | null }>(`/api/imports/${batch}`).then(result => result.cleanup)
        : request<{ job: Cleanup | null }>('/api/import-cleanup').then(result => result.job))
        .then(previous => { if (active && previous) setJobId(previous.id) }),
    ]
    void Promise.all(calls).catch(error => { if (active) setProblem(String(error.message)) })
      .finally(() => { if (active) setLoadingPrevious(false) })
    return () => { active = false }
  }, [batch, defaultDevice, request])

  const activeJob = !!job && activeStates.includes(job.state)
  useEffect(() => {
    if (!jobId) return
    let active = true, pending = false
    const read = async () => {
      if (pending) return
      pending = true
      try {
        const value = await request<Cleanup>(`/api/import-cleanup/${jobId}?offset=${offset}`)
        if (active) setJob(current => !current || current.id !== value.id || value.updated >= current.updated ? value : current)
      } catch (error) {
        if (active) setProblem(error instanceof Error ? error.message : String(error))
      } finally { pending = false }
    }
    void read()
    const timer = activeJob ? setInterval(() => void read(), 2400) : undefined
    return () => { active = false; clearInterval(timer) }
  }, [jobId, offset, request, activeJob])

  const selectionKey = job ? `${job.id}:${job.review}` : ''
  const allSelected = selection.key === selectionKey && selection.all
  const exceptions = selection.key === selectionKey ? selection.exceptions : emptySelection
  useEffect(() => { setOffset(0) }, [selectionKey])

  async function act(path: string, body: unknown, action: string) {
    setBusy(action); setProblem('')
    try {
      const value = await request<Cleanup>(path, body)
      setJobId(value.id)
      setJob(value)
      setOffset(0)
      setSelection({ key: '', all: false, exceptions: emptySelection })
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    } finally { setBusy('') }
  }
  function prepare(event: FormEvent) {
    event.preventDefault()
    void act(batch ? `/api/imports/${batch}/cleanup` : '/api/import-cleanup',
      { device, ...filter, since: filter.since || null, until: filter.until || null }, 'prepare')
  }
  function toggle(media: string) {
    setSelection(current => {
      const currentSelection = current.key === selectionKey ? current : { key: selectionKey, all: false, exceptions: emptySelection }
      const next = new Set(currentSelection.exceptions)
      if (next.has(media)) next.delete(media)
      else next.add(media)
      return { ...currentSelection, exceptions: next }
    })
  }
  const selected = job ? (allSelected ? job.count - exceptions.size : exceptions.size) : 0
  const hasMore = !!job && job.scanned < job.scan_total
  const canContinue = hasMore && (job.state === 'matched' || job.state === 'reviewed')
  const canResume = !!job && !!job.error && job.selected_remaining > 0
    && (job.state === 'reviewed' || job.state === 'cancelled')
  const canIncludeVideos = !!job && job.policy.source === 'whatsapp' && job.policy.kind === 'image'
    && (job.state === 'matched' || job.state === 'reviewed')
  const part = job?.scan_total
    ? Math.min(job.parts, Math.floor(Math.max(0, job.scanned - (job.state === 'finding' ? 0 : 1)) * job.parts / job.scan_total) + 1)
    : 1
  const invalidRange = !!(filter.since && filter.until && filter.since > filter.until)
  const deviceAvailable = devices.some(item => item.id === device)
  const loading = loadingPrevious || (!!jobId && !job)
  return <dialog ref={dialog} className="catalog-dialog" aria-labelledby="archive-cleanup-title" onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="catalog-dialog-heading">
      <h2 id="archive-cleanup-title">Libera spazio sul telefono</h2>
      <button onClick={onClose}>Chiudi</button>
    </div>
    <p>{batch ? 'Controlla le foto e i video di questo ZIP.' : 'Controlla le foto e i video delle importazioni completate.'}
      {' '}Sul PC restano gli originali e gli ZIP.</p>
    {!activeJob && !loading && <>
      <button type="button" onClick={() => setFilter(whatsAppPhotos)}>Foto WhatsApp fino al 31 dicembre 2024</button>
      <form className="catalog-toolbar" onSubmit={prepare}>
        <label>Telefono<select value={deviceAvailable ? device : ''} onChange={event => setDevice(event.target.value)} required>
          <option value="">Scegli un telefono associato</option>
          {devices.filter(item => !defaultDevice || item.id === defaultDevice).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label>Provenienza<select value={filter.source} onChange={event => setFilter({ ...filter, source: event.target.value })}>
          <option value="all">Tutte</option><option value="whatsapp">WhatsApp</option>
          <option value="telegram">Telegram</option><option value="normal">Fotocamera e altre cartelle</option>
        </select></label>
        <label>Tipo<select value={filter.kind} onChange={event => setFilter({ ...filter, kind: event.target.value })}>
          <option value="all">Foto e video</option><option value="image">Solo foto</option><option value="video">Solo video</option>
        </select></label>
        <label>Dal<input type="date" value={filter.since} onChange={event => setFilter({ ...filter, since: event.target.value })} /></label>
        <label>Al (incluso)<input type="date" value={filter.until} onChange={event => setFilter({ ...filter, until: event.target.value })} /></label>
        <button type="submit" disabled={!!busy || !deviceAvailable || invalidRange}>Prepara anteprima</button>
      </form>
      {invalidRange && <p role="alert">La data iniziale deve precedere quella finale.</p>}
      {filter.source === 'whatsapp' && <p className="catalog-muted">Per WhatsApp Regista usa la data più recente tra quella nel nome e quella del file sul telefono. Con un filtro per data, i file senza una data verificabile restano sul telefono.</p>}
    </>}
    {loading && <p role="status">Carico la selezione…</p>}
    {job && <section className="catalog-preview" aria-label="Anteprima rimozione">
      <h3>{job.state === 'matched' && hasMore ? 'Lotto pronto da rivedere' : states[job.state] || job.state}</h3>
      {job.policy.source && <p className="catalog-muted">{origins[job.policy.source]} · {kinds[job.policy.kind]}
        {job.policy.since && ` · dal ${formatDate(job.policy.since)}`}{job.policy.until && ` · fino al ${formatDate(job.policy.until)} incluso`}</p>}
      {job.scan_total > 0 && <div>
        <label>Lotto {part} di {Math.min(job.parts, job.scan_total)} · {number.format(job.scanned)} di {number.format(job.scan_total)} originali controllati
          {' '}<progress value={job.scanned} max={job.scan_total} /></label>
      </div>}
      <p role="status">{number.format(job.count)} corrispondenze nel lotto · {number.format(job.images)} foto · {number.format(job.videos)} video
        {job.selected > 0 && ` · ${number.format(job.selected)} confermati`}
        {job.removed > 0 && ` · ${number.format(job.removed)} rimossi in tutto`}</p>
      {job.state === 'finding' && <>
        <p className="catalog-muted">Apri Regista sul telefono per avviare il lotto. Quando appare la notifica di verifica puoi spegnere lo schermo.</p>
        <button type="button" disabled={!!busy} onClick={() => void act(`/api/import-cleanup/${job.id}/pause`, { review: job.review }, 'pause')}>
          {job.count ? 'Rivedi i file trovati finora' : 'Metti in pausa'}
        </button>
      </>}
      {job.error && <p role="alert">{job.error}</p>}
      {canResume && <button type="button" disabled={!!busy} onClick={() => void act(
        `/api/import-cleanup/${job.id}/resume-removal`, { review: job.review }, 'resume-removal')}>
        Riprendi la rimozione di {number.format(job.selected_remaining)} file
      </button>}
      {job.state === 'matched' && !job.count && <p>Nessun file in questo lotto corrisponde al filtro.</p>}
      {job.state === 'matched' && job.count > 0 && <>
        <p>Lascia la spunta sulle foto e sui video da togliere. Regista verifica lo ZIP e la copia normale prima di chiederti conferma sul telefono.</p>
        <div className="catalog-toolbar">
          <button type="button" disabled={!!busy} onClick={() => setSelection({ key: selectionKey, all: true, exceptions: emptySelection })}>Seleziona tutti</button>
          <button type="button" disabled={!!busy} onClick={() => setSelection({ key: selectionKey, all: false, exceptions: emptySelection })}>Deseleziona tutti</button>
          <span>{selected} selezionati su {job.count}</span>
        </div>
        {job.offset === offset && <div className="archive-file-list"><table>
          <thead><tr><th>Da togliere</th><th>File e cartella originale</th><th>Data sul telefono</th></tr></thead>
          <tbody>{job.files.map(file => <tr key={file.media}>
            <td><input type="checkbox" aria-label={`Rimuovi ${file.name} da ${file.folder}`} disabled={!!busy}
              checked={allSelected !== exceptions.has(file.media)} onChange={() => toggle(file.media)} /></td>
            <td><div className="archive-file-preview"><a href={`/api/catalog/photos/${file.sha256}/full`} download aria-label={`Scarica ${file.name} sul PC`}>
              <img src={`/api/catalog/photos/${file.sha256}/thumb`} alt="" loading="lazy" /></a>
              <span>{file.kind === 'video' && 'Video · '}{file.name}<small>{file.folder}</small></span></div></td>
            <td>{file.day ? formatDate(file.day) : 'Data non disponibile'}<small>{dateSources[file.date_source]}</small></td>
          </tr>)}</tbody>
        </table></div>}
        {job.count > job.limit && <div className="catalog-toolbar">
          <button disabled={!offset || !!busy} onClick={() => setOffset(Math.max(0, offset - job.limit))}>Precedenti</button>
          <span>{offset + 1}–{Math.min(offset + job.limit, job.count)} di {job.count}</span>
          <button disabled={offset + job.limit >= job.count || !!busy} onClick={() => setOffset(offset + job.limit)}>Successivi</button>
        </div>}
        {job.folder_files > 0 && <p className="catalog-muted">Per i file nelle cartelle autorizzate il telefono può chiederti di scegliere la cartella e confermare la rimozione diretta.</p>}
        <button disabled={!!busy || !selected} onClick={() => void act(`/api/import-cleanup/${job.id}/confirm`,
          { yes: true, review: job.review, [allSelected ? 'keep' : 'only']: [...exceptions] }, 'confirm')}>
          {busy === 'confirm' ? 'Verifico ZIP e copie sul PC…' : `Conferma rimozione di ${selected} file dal telefono`}
        </button>
      </>}
      {canContinue && <button type="button" disabled={!!busy} onClick={() => void act(`/api/import-cleanup/${job.id}/continue`, { review: job.review }, 'continue')}>
        {job.state === 'matched' && job.count > 0 ? 'Conserva i file del lotto e continua' : 'Continua la verifica'}
      </button>}
      {canIncludeVideos && <button type="button" disabled={!!busy} onClick={() => void act(
        `/api/import-cleanup/${job.id}/include-videos`, { review: job.review }, 'include-videos')}>
        {busy === 'include-videos' ? 'Aggiungo i video…' : 'Includi anche i video WhatsApp'}
      </button>}
      {activeJob && <button disabled={!!busy} onClick={() => void act(`/api/import-cleanup/${job.id}/confirm`, { yes: false, review: job.review }, 'cancel')}>
        {job.state === 'approved' ? 'Interrompi la richiesta' : 'Annulla verifica'}</button>}
      {job.state === 'approved' && <p className="catalog-muted">Se la conferma Android è già aperta, puoi scegliere «Conserva» o «Annulla» sul telefono.</p>}
    </section>}
    {problem && <p role="alert" className="catalog-alert">{problem}</p>}
  </dialog>
}
