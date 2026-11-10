import { useEffect, useMemo, useRef, useState } from 'react'
import { applyCommandTags } from './bridge.ts'
import type { CommandTagEdit, CommandTagSearch } from './bridge.ts'
import type { Picture } from './select.ts'

export type TagCommand = { action: CommandTagEdit; tag: string } | { search: CommandTagSearch }

type Props = { command: TagCommand; pictures: Picture[]; thumb: (id: string) => string }

const PAGE = 120
const MAX_SELECTED = 120

export default function CommandTags({ command, pictures, thumb }: Props) {
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [review, setReview] = useState(false)
  const [changed, setChanged] = useState<number | null>(null)
  const [problem, setProblem] = useState('')
  const summary = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (review || changed !== null) summary.current?.scrollIntoView({ block: 'nearest' })
  }, [review, changed])
  const byId = useMemo(() => new Map(pictures.map((photo) => [photo.id, photo])), [pictures])
  const shown = useMemo(() => {
    if (!('search' in command)) return pictures
    if ('error' in command.search) return []
    const matches = new Set(command.search.ids)
    return pictures.filter((photo) => matches.has(photo.id))
  }, [command, pictures])
  const editing = 'action' in command
  const shownPage = Math.min(page, Math.max(0, Math.ceil(shown.length / PAGE) - 1))

  function toggle(id: string) {
    setSelected((before) => before.includes(id)
      ? before.filter((one) => one !== id)
      : before.length < MAX_SELECTED ? [...before, id] : before)
  }

  function confirm() {
    if (!('action' in command) || !review || !selected.length) return
    if (selected.some((id) => !byId.has(id))) {
      setProblem('Una foto selezionata non è più visibile. Scegli di nuovo le foto.')
      setSelected((ids) => ids.filter((id) => byId.has(id)))
      setReview(false)
      return
    }
    const result = applyCommandTags(command.action, command.tag, selected)
    if ('error' in result) {
      setProblem(result.error)
    } else {
      setProblem('')
      setReview(false)
      setChanged(result.changed)
    }
  }

  if ('search' in command && 'error' in command.search) return <p role="alert">{command.search.error}</p>
  if (changed !== null) {
    return <p ref={summary} role="status">{changed === 0 ? 'Nessun tag da aggiornare.' : changed === 1 ? 'Tag aggiornato per 1 foto.' : `Tag aggiornato per ${changed} foto.`}</p>
  }

  return (
    <section className="command-tags" aria-label={editing ? 'Scegli le foto per il tag' : 'Risultati della ricerca per tag'}>
      {problem && <p role="alert">{problem}</p>}
      {editing && review ? (
        <>
          <p ref={summary}>{command.action === 'add_tag' ? 'Aggiungi' : 'Togli'} il tag «{command.tag}» per queste foto</p>
          <ul className="tag-photo-names">
            {selected.map((id) => <li key={id}>{byId.get(id)?.name ?? 'Foto non più visibile'}</li>)}
          </ul>
          <div className="tag-controls">
            <button type="button" className="go" onClick={confirm}>Conferma modifica tag</button>
            <button type="button" className="quiet" onClick={() => { setProblem(''); setReview(false) }}>Torna alla scelta</button>
          </div>
        </>
      ) : (
        <>
          <p role="status">{editing ? `${selected.length} selezionate (massimo ${MAX_SELECTED})` : `${shown.length} foto con questo tag`}</p>
          {shown.length === 0 ? <p>Nessuna foto da mostrare.</p> : (
            <ul className="grid">
              {shown.slice(shownPage * PAGE, (shownPage + 1) * PAGE).map((photo) => (
                <li key={photo.id} className="tag-photo">
                  {editing ? (
                    <label>
                      <img className="tile" src={thumb(photo.id)} alt="" loading="lazy" />
                      <span>
                        <input
                          type="checkbox"
                          checked={selected.includes(photo.id)}
                          disabled={selected.length === MAX_SELECTED && !selected.includes(photo.id)}
                          onChange={() => toggle(photo.id)}
                        />
                        {photo.name}
                      </span>
                    </label>
                  ) : (
                    <>
                      <img className="tile" src={thumb(photo.id)} alt="" loading="lazy" />
                      <span>{photo.name}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="tag-controls">
            {shownPage > 0 && <button type="button" className="quiet" onClick={() => setPage(shownPage - 1)}>Foto precedenti</button>}
            {(shownPage + 1) * PAGE < shown.length && <button type="button" className="quiet" onClick={() => setPage(shownPage + 1)}>Foto successive</button>}
            {editing && <button type="button" className="go" disabled={!selected.length} onClick={() => { setProblem(''); setReview(true) }}>Rivedi modifica</button>}
          </div>
        </>
      )}
    </section>
  )
}
