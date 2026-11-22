import { useState } from 'react'
import type { CatalogRequest } from './catalogApi.ts'
import type { TagUsage } from './CatalogTags.tsx'

type Preview = { preview_id: string; count: number; tags: string[]; album: string; hidden: boolean | null; sample_ids: string[] }
export default function CatalogBulk({ selected, plan, total, request, knownTags, onChanged }: {
  selected: string[]; plan: Record<string, unknown>; total: number; request: CatalogRequest; knownTags: TagUsage[]; onChanged: () => Promise<void>
}) {
  const selectionKey = JSON.stringify([selected, plan])
  const [allFor, setAllFor] = useState('')
  const all = allFor === selectionKey
  const [tags, setTags] = useState('')
  const [album, setAlbum] = useState('')
  const [visibility, setVisibility] = useState('keep')
  const [command, setCommand] = useState('')
  const [savedPreview, setSavedPreview] = useState<{ value: Preview; key: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const previewKey = JSON.stringify([selectionKey, all, tags, album, visibility, command])
  const preview = savedPreview?.key === previewKey ? savedPreview.value : null
  const setPreview = (value: Preview | null) => setSavedPreview(value ? { value, key: previewKey } : null)
  async function work(action: () => Promise<void>) {
    setBusy(true); setMessage('')
    try { await action() } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }
  return <details className="catalog-panel catalog-bulk"><summary>Tag e album per una selezione · {all ? total : selected.length} elementi</summary>
    <p className="catalog-muted">Seleziona un primo elemento, poi Maiusc + clic sull’ultimo per includere l’intervallo nella pagina. Per intervalli più grandi usa le date e “Tutti i risultati”.</p>
    <label className="catalog-check"><input type="checkbox" checked={all} onChange={e => setAllFor(e.target.checked ? selectionKey : '')} />Tutti i {total} risultati della ricerca, comprese le altre pagine</label>
    <div className="catalog-filters">
      <label>Tag separati da virgole<input value={tags} onChange={e => setTags(e.target.value)} placeholder="Skopje, Macedonia" maxLength={4000} /></label>
      <label>Aggiungi un tag esistente<select value="" onChange={event => {
        const tag = event.target.value
        if (tag) setTags(before => [...new Set([...before.split(',').map(value => value.trim()).filter(Boolean), tag])].join(', '))
      }}><option value="">Scegli un tag</option>{knownTags.map(item => <option key={item.tag} value={item.tag}>{item.tag} ({item.count})</option>)}</select></label>
      <label>Album / cartella virtuale<input value={album} onChange={e => setAlbum(e.target.value)} placeholder="Viaggio a Skopje" maxLength={120} /></label>
      <label>Visibilità<select value={visibility} onChange={e => setVisibility(e.target.value)}><option value="keep">Mantieni</option><option value="hide">Nascondi dalla vista generale</option><option value="show">Rendi visibili</option></select></label>
    </div>
    <button disabled={busy || !(all ? total : selected.length)} onClick={() => void work(async () => setPreview(await request<Preview>('/api/catalog/bulk/preview', {
      ids: selected, plan, select_all: all, tags, album, hidden: visibility === 'keep' ? null : visibility === 'hide',
    })))}>Controlla anteprima</button>
    <details><summary>Proponi la selezione con Qwen</summary><form onSubmit={event => {
      event.preventDefault(); void work(async () => setPreview(await request<Preview>('/api/catalog/bulk/propose', { text: command })))
    }}><label>Descrivi date e tag<input value={command} onChange={e => setCommand(e.target.value)} placeholder="Dal 10 al 18 maggio 2025 aggiungi Skopje e Macedonia, album Viaggio a Skopje" maxLength={4000} required /></label><button disabled={busy}>Prepara proposta</button></form></details>
    {preview && <div className="catalog-preview" role="region" aria-label="Anteprima modifica">
      <p><b>{preview.count} foto e video</b>{preview.tags.length > 0 && ` · Tag: ${preview.tags.join(', ')}`}{preview.album && ` · Album: ${preview.album}`}{preview.hidden !== null && (preview.hidden ? ' · Da nascondere' : ' · Da rendere visibili')}</p>
      <div className="catalog-preview-images">{preview.sample_ids.map(id => <img key={id} src={`/api/catalog/photos/${id}/thumb`} alt="Elemento della selezione proposta" loading="lazy" />)}</div>
      <p className="catalog-muted">Questi sono alcuni elementi della selezione. La conferma applica i metadati a tutti i {preview.count} elementi indicati.</p>
      <button disabled={busy} onClick={() => void work(async () => {
        const result = await request<{ updated: number }>('/api/catalog/bulk/apply', { preview_id: preview.preview_id })
        setPreview(null); await onChanged(); setMessage(`Aggiornati ${result.updated} elementi.`)
      })}>Conferma modifica a {preview.count} elementi</button>
      <button disabled={busy} onClick={() => setPreview(null)}>Annulla proposta</button>
    </div>}
    {busy && <p role="status">Preparo e verifico la selezione…</p>}
    {message && <p role="status">{message}</p>}
  </details>
}
