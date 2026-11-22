import { useEffect, useRef, useState } from 'react'
import type { CatalogRequest } from './catalogApi.ts'
import ArchiveCleanupDialog from './ArchiveCleanupDialog.tsx'

type Batch = { id: string; device: string; total: number; confirmed: number; copied: number; duplicates: number; state: string;
  created: number; source: string; document_type?: string; images: number; videos: number; audio: number; documents?: number;
  archive_members: number; zip_ready: boolean; error: string; transport: string }
type FileItem = { media: string; name: string; folder: string; kind: string; day: string; sha256: string; size: number }
type Detail = Batch & { files: FileItem[]; offset: number }
const states: Record<string, string> = { copying: 'Copia in corso', finalizing: 'Verifica del blocco', error: 'Da verificare' }
const label = (batch: Batch) => batch.state === 'ready'
  ? batch.zip_ready ? 'ZIP verificato' : 'Già archiviati sul PC'
  : states[batch.state] || batch.state
const channel = (value: string) => ({ usb: 'Cavo USB', wifi: 'Wi-Fi', wired: 'Rete cablata', local: 'Rete privata / VPN' }[value] || 'Canale da verificare')

export default function ImportArchives({ request }: { request: CatalogRequest }) {
  const [batches, setBatches] = useState<Batch[]>([])
  const [chosen, setChosen] = useState('')
  const [cleanup, setCleanup] = useState<{ id: string; device: string } | 'library' | null>(null)
  const [problem, setProblem] = useState('')
  useEffect(() => {
    let active = true
    const read = () => request<{ imports: Batch[] }>('/api/imports').then(result => { if (active) setBatches(result.imports) }, error => { if (active) setProblem(String(error.message)) })
    void read(); const timer = setInterval(() => void read(), 3000)
    return () => { active = false; clearInterval(timer) }
  }, [request])
  return <section className="catalog-panel" aria-label="Importazioni e archivi ZIP"><h2>Importazioni e archivi</h2>
    <p className="catalog-muted">Il PC conserva tutti gli originali. Ogni nuovo ZIP contiene i file del blocco ancora da archiviare e viene verificato prima di essere chiuso.</p>
    {batches.some(batch => batch.state === 'ready' && batch.images + batch.videos > 0) &&
      <button onClick={() => setCleanup('library')}>Rivedi cosa togliere dal telefono</button>}
    {!batches.length && <p className="catalog-muted">Nessuna nuova importazione. Avviala dal telefono o dal pulsante Importa.</p>}
    {batches.map((batch, index) => <button className="archive-card" key={batch.id} onClick={() => setChosen(batch.id)}>
      <span><b>{batch.source === 'whatsapp' ? 'WhatsApp' : batch.source === 'telegram' ? 'Telegram' : 'Telefono'} · Blocco {batches.length - index}</b><small>{new Date(batch.created * 1000).toLocaleString('it-IT')} · {label(batch)} · {channel(batch.transport)}</small></span>
      <span>{batch.confirmed} / {batch.total}<small>{batch.documents ? `${batch.documents} ${batch.document_type?.toUpperCase() || 'documenti'}` : `${batch.images} foto · ${batch.videos} video`}{batch.audio > 0 && ` · ${batch.audio} audio`}</small></span>
      <progress value={batch.confirmed} max={Math.max(1, batch.total)} aria-label="Originali ricevuti" />
      {batch.error && <small>{batch.error}</small>}
    </button>)}
    {problem && <p role="alert">{problem}</p>}
    {chosen && <ArchiveDetail id={chosen} request={request} onClose={() => setChosen('')} onCleanup={setCleanup} />}
    {cleanup && <ArchiveCleanupDialog archive={cleanup === 'library' ? null : cleanup} request={request} onClose={() => setCleanup(null)} />}
  </section>
}

function ArchiveDetail({ id, request, onClose, onCleanup }: {
  id: string; request: CatalogRequest; onClose: () => void; onCleanup: (batch: { id: string; device: string }) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [offset, setOffset] = useState(0)
  const [problem, setProblem] = useState('')
  useEffect(() => { dialog.current?.showModal() }, [])
  useEffect(() => {
    let active = true, pending = false
    const read = async () => {
      if (pending) return
      pending = true
      try {
        const value = await request<Detail>(`/api/imports/${id}?offset=${offset}`)
        if (active) setDetail(value)
      } catch (error) { if (active) setProblem(error instanceof Error ? error.message : String(error)) }
      finally { pending = false }
    }
    void read(); const timer = setInterval(() => void read(), 2000)
    return () => { active = false; clearInterval(timer) }
  }, [id, offset, request])
  return <dialog ref={dialog} className="catalog-dialog" aria-labelledby="archive-title" onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="catalog-dialog-heading"><h2 id="archive-title">Archivio del blocco</h2><button onClick={onClose} aria-label="Chiudi archivio">Chiudi</button></div>
    {detail && <><p>{label(detail)} · {detail.confirmed} / {detail.total} file</p>
      <p className="catalog-muted">{detail.copied} copiati · {detail.duplicates} già presenti · {channel(detail.transport)}</p>
      {detail.zip_ready && <p><a href={`/api/imports/${id}/zip`} download>Scarica lo ZIP ({detail.archive_members} originali)</a></p>}
      {detail.state === 'ready' && !detail.zip_ready && <p>Gli originali di questo blocco sono già protetti dagli archivi precedenti.</p>}
      <div className="archive-file-list"><table><thead><tr><th>File</th><th>Cartella originale</th><th>Data</th></tr></thead><tbody>{detail.files.map(file => <tr key={file.media}><td>{file.kind === 'video' ? 'Video · ' : file.kind === 'audio' ? 'Audio · ' : ''}{file.name}</td><td>{file.folder || 'Non disponibile'}</td><td>{file.day}</td></tr>)}</tbody></table></div>
      <div className="catalog-toolbar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Precedenti</button><span>{offset + 1}–{offset + detail.files.length}</span><button disabled={offset + detail.files.length >= detail.total} onClick={() => setOffset(offset + 100)}>Successive</button></div>
      {detail.zip_ready && detail.images + detail.videos > 0 &&
        <button onClick={() => onCleanup({ id, device: detail.device })}>Libera spazio dal telefono con questo ZIP</button>}
    </>}
    {problem && <p role="alert">{problem}</p>}
  </dialog>
}
