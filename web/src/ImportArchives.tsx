import { useEffect, useRef, useState } from 'react'
import type { CatalogRequest } from './catalogApi.ts'

type Batch = { id: string; device: string; total: number; confirmed: number; copied: number; duplicates: number; state: string;
  created: number; source: string; document_type?: string; images: number; videos: number; audio: number; documents?: number; zip_ready: boolean; error: string; transport: string }
type FileItem = { media: string; name: string; folder: string; kind: string; day: string; sha256: string; size: number }
type Detail = Batch & { files: FileItem[]; offset: number; cleanup: { id: string } | null }
type Cleanup = { id: string; state: string; count: number; images: number; videos: number; removed: number; error: string; pc_copies_verified: boolean; files: FileItem[] }
const states: Record<string, string> = { copying: 'Copia in corso', finalizing: 'Creazione e verifica ZIP', ready: 'Copie normali e ZIP pronti', error: 'Da verificare' }
const cleanupStates: Record<string, string> = { verifying: 'Verifico ZIP e copie normali sul PC…', finding: 'Apri Regista sul telefono: cerco gli originali corrispondenti allo SHA…',
  matched: 'Selezione pronta da confermare', approved: 'Conferma anche nella finestra Android sul telefono.', finished: 'Operazione conclusa', cancelled: 'Operazione annullata', error: 'Verifica non riuscita' }
const channel = (value: string) => ({ usb: 'Cavo USB', wifi: 'Wi-Fi', wired: 'Rete cablata', local: 'Rete privata / VPN' }[value] || 'Canale da verificare')

export default function ImportArchives({ request }: { request: CatalogRequest }) {
  const [batches, setBatches] = useState<Batch[]>([])
  const [chosen, setChosen] = useState('')
  const [problem, setProblem] = useState('')
  useEffect(() => {
    let active = true
    const read = () => request<{ imports: Batch[] }>('/api/imports').then(result => { if (active) setBatches(result.imports) }, error => { if (active) setProblem(String(error.message)) })
    void read(); const timer = setInterval(() => void read(), 3000)
    return () => { active = false; clearInterval(timer) }
  }, [request])
  return <section className="catalog-panel" aria-label="Importazioni e archivi ZIP"><h2>Importazioni e archivi</h2>
    <p className="catalog-muted">Un blocco conserva la selezione iniziale. Lo ZIP viene creato alla fine, dopo la verifica di tutti i file, e rimane invariato.</p>
    {!batches.length && <p className="catalog-muted">Nessuna nuova importazione. Avviala dal telefono o dal pulsante Importa.</p>}
    {batches.map((batch, index) => <button className="archive-card" key={batch.id} onClick={() => setChosen(batch.id)}>
      <span><b>{batch.source === 'whatsapp' ? 'WhatsApp' : batch.source === 'telegram' ? 'Telegram' : 'Telefono'} · Blocco {batches.length - index}</b><small>{new Date(batch.created * 1000).toLocaleString('it-IT')} · {states[batch.state] || batch.state} · {channel(batch.transport)}</small></span>
      <span>{batch.confirmed} / {batch.total}<small>{batch.documents ? `${batch.documents} ${batch.document_type?.toUpperCase() || 'documenti'}` : `${batch.images} foto · ${batch.videos} video`}{batch.audio > 0 && ` · ${batch.audio} audio`}</small></span>
      <progress value={batch.confirmed} max={Math.max(1, batch.total)} aria-label="Originali ricevuti" />
      {batch.error && <small>{batch.error}</small>}
    </button>)}
    {problem && <p role="alert">{problem}</p>}
    {chosen && <ArchiveDetail id={chosen} request={request} onClose={() => setChosen('')} />}
  </section>
}

function ArchiveDetail({ id, request, onClose }: { id: string; request: CatalogRequest; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [offset, setOffset] = useState(0)
  const [devices, setDevices] = useState<{ id: string; name: string }[]>([])
  const [device, setDevice] = useState('')
  const [cleanup, setCleanup] = useState<Cleanup | null>(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { dialog.current?.showModal() }, [])
  useEffect(() => {
    let active = true, pending = false
    const read = async () => {
      if (pending) return
      pending = true
      try {
        const value = await request<Detail>(`/api/imports/${id}?offset=${offset}`)
        if (active) setDetail(value)
        if (value.cleanup) { const status = await request<Cleanup>(`/api/import-cleanup/${value.cleanup.id}`); if (active) setCleanup(status) }
      } catch (error) { if (active) setProblem(error instanceof Error ? error.message : String(error)) }
      finally { pending = false }
    }
    void read(); const timer = setInterval(() => void read(), 2000)
    void request<{ devices: { id: string; name: string }[] }>('/api/phone').then(value => { if (active) setDevices(value.devices) }, () => {})
    return () => { active = false; clearInterval(timer) }
  }, [id, offset, request])
  async function act(path: string, body: unknown) {
    setBusy(true); setProblem('')
    try { setCleanup(await request<Cleanup>(path, body)) }
    catch (error) { setProblem(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }
  return <dialog ref={dialog} className="catalog-dialog" aria-labelledby="archive-title" onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="catalog-dialog-heading"><h2 id="archive-title">Archivio del blocco</h2><button onClick={onClose} aria-label="Chiudi archivio">Chiudi</button></div>
    {detail && <><p>{states[detail.state]} · {detail.confirmed} / {detail.total} file</p>
      <p className="catalog-muted">{detail.copied} copiati · {detail.duplicates} già presenti · {channel(detail.transport)}</p>
      {detail.zip_ready && <p><a href={`/api/imports/${id}/zip`} download>Scarica lo ZIP completo</a></p>}
      <div className="archive-file-list"><table><thead><tr><th>File</th><th>Cartella originale</th><th>Data</th></tr></thead><tbody>{detail.files.map(file => <tr key={file.media}><td>{file.kind === 'video' ? 'Video · ' : file.kind === 'audio' ? 'Audio · ' : ''}{file.name}</td><td>{file.folder || 'Non disponibile'}</td><td>{file.day}</td></tr>)}</tbody></table></div>
      <div className="catalog-toolbar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Precedenti</button><span>{offset + 1}–{offset + detail.files.length}</span><button disabled={offset + detail.files.length >= detail.total} onClick={() => setOffset(offset + 100)}>Successive</button></div>
      {detail.zip_ready && detail.images+detail.videos>0 && <section className="catalog-preview"><h3>Libera spazio sul telefono</h3><p>Rimuovi solo foto e video che corrispondono al contenuto di questo ZIP. Verifico di nuovo sia lo ZIP sia le copie normali prima di autorizzare il cestino Android.</p>
        <label>Telefono da controllare<select value={device || detail.device} onChange={e => setDevice(e.target.value)}>{!devices.some(item => item.id === (device || detail.device)) && <option value="">Seleziona un telefono collegato</option>}{devices.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <button disabled={busy || !devices.some(item => item.id === (device || detail.device)) || !!(cleanup && !['finished', 'cancelled', 'error'].includes(cleanup.state))}
          onClick={() => void act(`/api/imports/${id}/cleanup`, { device: device || detail.device })}>Elimina dal telefono i file presenti in questo ZIP…</button>
        <p className="catalog-muted">Tieni Regista aperto sul telefono. La ricerca prepara un’anteprima; poi servono la tua conferma qui e quella di Android.</p>
        {cleanup && <div role="status"><p>{cleanupStates[cleanup.state] || cleanup.state}</p>
          <p>{cleanup.count} corrispondenze · {cleanup.images} foto · {cleanup.videos} video · {cleanup.removed} spostati nel cestino</p>
          {cleanup.error && <p role="alert">{cleanup.error}</p>}
          {cleanup.state === 'matched' && <><details><summary>Controlla i file trovati</summary><ul>{cleanup.files.map(file => <li key={file.media}>{file.folder}/{file.name}</li>)}</ul></details><button disabled={busy || !cleanup.count} onClick={() => void act(`/api/import-cleanup/${cleanup.id}/confirm`, { yes: true })}>Confermo: sposta {cleanup.count} originali nel cestino del telefono</button></>}
          {!['finished', 'cancelled', 'error'].includes(cleanup.state) && <button disabled={busy} onClick={() => void act(`/api/import-cleanup/${cleanup.id}/confirm`, { yes: false })}>Annulla eliminazione</button>}
        </div>}
      </section>}
    </>}
    {problem && <p role="alert">{problem}</p>}
  </dialog>
}
