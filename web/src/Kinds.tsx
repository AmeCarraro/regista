import { useEffect, useState } from 'react'
import { fetchKind, fetchKinds } from './api.ts'
import type { Found, Kind } from './api.ts'
import * as icons from './icons.tsx'
import PhotoResults, { Thumb } from './Photos.tsx'

// how many pictures are shown at first, and how many more at each "Mostrane altre"
const PAGE = 240

/**
 * The pictures by kind, one folder for each, and "Tutte" with all of them: a way of looking at the
 * library that moves nothing. On the disk every picture stays where it is.
 */
export default function Kinds({ visible }: { visible: boolean }) {
  const [kinds, setKinds] = useState<Kind[] | null>(null)
  const [total, setTotal] = useState(0)
  const [open, setOpen] = useState<{ kind: string; label: string } | null>(null)
  const [found, setFound] = useState<Found | null>(null)
  const [shown, setShown] = useState(PAGE)
  const [problem, setProblem] = useState('')

  // worked out again each time they are shown: pictures may have been added to the folder meanwhile
  useEffect(() => {
    if (!visible) return
    fetchKinds().then(
      (listed) => {
        setProblem('')
        setKinds(listed.kinds)
        setTotal(listed.total)
      },
      (error: unknown) => setProblem(error instanceof Error ? error.message : String(error)),
    )
  }, [visible])

  function choose(kind: string, label: string) {
    setOpen({ kind, label })
    setFound(null)
    setShown(PAGE)
    fetchKind(kind).then(setFound, (error: unknown) => setProblem(error instanceof Error ? error.message : String(error)))
  }

  return (
    <section className="kinds" hidden={!visible}>
      {open ? (
        <>
          <div className="kinds-top">
            <button type="button" className="round ghost small" aria-label="Tutti i tipi" onClick={() => setOpen(null)}>
              <icons.Back />
            </button>
            <h2>{open.label}</h2>
            {found && <span className="fine">{found.matching} foto</span>}
          </div>
          {found && found.maybe.length > 0 && (
            <p className="fine">Prima quelle di cui sono sicuro, poi, più chiare, le altre: il tipo lo decide il modello delle immagini, e può sbagliare.</p>
          )}
          {found ? (
            <>
              <PhotoResults all found={{ ...found, sure: found.sure.slice(0, shown), maybe: found.maybe.slice(0, Math.max(0, shown - found.sure.length)) }} />
              {found.sure.length + found.maybe.length > shown && (
                <button type="button" className="link" onClick={() => setShown(shown + PAGE)}>
                  Mostrane altre ({found.sure.length + found.maybe.length - shown})
                </button>
              )}
            </>
          ) : (
            <p className="fine">Un attimo…</p>
          )}
        </>
      ) : (
        <>
          <div className="kinds-top">
            <h2>Le foto per tipo</h2>
            <span className="fine">Nessuna foto è stata spostata: sul disco sono dove erano.</span>
          </div>
          {problem && <p className="fine warn">Non riesco a dividere le foto: {problem}</p>}
          {kinds?.length === 0 && <p className="fine">Non ho ancora foto: quando avrò letto la cartella, le troverai qui divise per tipo.</p>}
          <ul className="folders">
            {kinds && kinds.length > 0 && (
              <li>
                <button type="button" className="folder" onClick={() => choose('tutte', 'Tutte')}>
                  <span className="cover all">
                    <icons.Picture />
                  </span>
                  <b>Tutte</b>
                  <small>{total} foto</small>
                </button>
              </li>
            )}
            {kinds?.map((kind) => (
              <li key={kind.kind}>
                <button type="button" className="folder" onClick={() => choose(kind.kind, kind.label)}>
                  <span className="cover">
                    <Thumb id={kind.cover} />
                  </span>
                  <b>{kind.label}</b>
                  <small>{kind.count} foto</small>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
