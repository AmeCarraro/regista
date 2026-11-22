import { useEffect, useState } from 'react'
import type { CatalogRequest } from './catalogApi.ts'

export type TagUsage = { tag: string; count: number; automatic: number }
export type TagPage = { tags: TagUsage[]; total: number }

export default function CatalogTags({ request, revision, onChoose }: {
  request: CatalogRequest; revision: number; onChoose: (tag: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [result, setResult] = useState<TagPage | null>(null)
  const [problem, setProblem] = useState('')
  useEffect(() => {
    if (!open) return
    let active = true
    const timer = setTimeout(() => {
      void request<TagPage>(`/api/catalog/tags?q=${encodeURIComponent(query)}&offset=${offset}`).then(
        value => { if (active) { setResult(value); setProblem('') } },
        error => { if (active) setProblem(String(error.message)) },
      )
    }, 180)
    return () => { active = false; clearTimeout(timer) }
  }, [open, query, offset, request, revision])
  return <details className="catalog-panel" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Tag del catalogo</summary>
    <label>Cerca un tag<input value={query} maxLength={100} onChange={event => { setQuery(event.target.value); setOffset(0) }} /></label>
    {problem && <p role="alert">{problem}</p>}
    {result && <><p className="catalog-muted" role="status">{result.total} tag trovati. Scegline uno per vedere le foto e i video associati.</p>
      <div className="catalog-toolbar">{result.tags.map(item => <button key={item.tag} type="button" title={`${item.automatic} assegnazioni di Qwen`}
        onClick={() => onChoose(item.tag)}>{item.tag} · {item.count}</button>)}</div>
      {result.total > 80 && <div className="catalog-toolbar"><button type="button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 80))}>Tag precedenti</button>
        <button type="button" disabled={offset + 80 >= result.total} onClick={() => setOffset(offset + 80)}>Altri tag</button></div>}
    </>}
  </details>
}
