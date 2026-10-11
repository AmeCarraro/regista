import { useContext, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { CSSProperties } from 'react'
import { fullOf, thumbOf } from './api.ts'
import type { Found, Photo } from './api.ts'
import * as icons from './icons.tsx'
import { Shelf } from './shelf.ts'

/**
 * The small copy of a picture. If it cannot be loaded, because the picture is
 * being read again or is no longer there, a quiet placeholder takes its place
 * until the library changes; then it is asked for again.
 */
export function Thumb({ id }: { id: string }) {
  const { epoch } = useContext(Shelf)
  const [failedAt, setFailedAt] = useState<string | null>(null)
  if (failedAt === epoch) {
    return (
      <span className="no-thumb">
        <icons.Picture />
      </span>
    )
  }
  return <img src={thumbOf(id)} alt="" loading="lazy" onError={() => setFailedAt(epoch)} />
}

/** One picture at full size over the page, with the others of the same search one key away. */
function Lightbox({ photos, at, onMove, onClose }: { photos: Photo[]; at: number; onMove: (to: number) => void; onClose: () => void }) {
  const photo = photos[at]

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
      if (event.key === 'ArrowRight') onMove(Math.min(at + 1, photos.length - 1))
      if (event.key === 'ArrowLeft') onMove(Math.max(at - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [at, photos.length, onMove, onClose])

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={photo.name} onClick={onClose}>
      <button type="button" className="round ghost close" aria-label="Chiudi" onClick={onClose}>
        <icons.Cross />
      </button>
      {at > 0 && (
        <button
          type="button"
          className="round ghost previous"
          aria-label="Foto precedente"
          onClick={(event) => {
            event.stopPropagation()
            onMove(at - 1)
          }}
        >
          <icons.Back />
        </button>
      )}
      <figure onClick={(event) => event.stopPropagation()}>
        <img src={fullOf(photo.id)} alt={photo.name} />
        <figcaption>
          <span className="mono">{photo.name}</span>
          <span>
            {at + 1} di {photos.length}
          </span>
        </figcaption>
      </figure>
      {at < photos.length - 1 && (
        <button
          type="button"
          className="round ghost next"
          aria-label="Foto successiva"
          onClick={(event) => {
            event.stopPropagation()
            onMove(at + 1)
          }}
        >
          <icons.Arrow />
        </button>
      )}
    </div>
  )
}

/**
 * What a search found: the pictures the app is sure about, and behind a button
 * the ones it is less sure about. A click opens a picture at full size. A picture
 * that went to the trash since stays in its place, faded: it shows what happened.
 */
export default function PhotoResults({ found }: { found: Found }) {
  const { gone } = useContext(Shelf)
  const [more, setMore] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  // with nothing sure to show, the maybes are all there is: no point in hiding them
  const unsureOnly = found.sure.length === 0
  const shown = more || unsureOnly ? [...found.sure, ...found.maybe] : found.sure
  if (shown.length === 0) return null
  // only what is still there can be opened
  const there = shown.filter((photo) => !gone.has(photo.id))
  const at = there.findIndex((photo) => photo.id === open)

  return (
    <div className="results">
      <div className="grid">
        {shown.map((photo, index) => {
          const away = gone.has(photo.id)
          // the same button either way: the small copy already on screen stays there, faded, when its picture goes
          return (
            <button
              key={photo.id}
              type="button"
              className={`photo${index >= found.sure.length ? ' unsure' : ''}${away ? ' gone' : ''}`}
              style={{ '--i': Math.min(index, 24) } as CSSProperties}
              aria-label={away ? `${photo.name}, nel cestino` : `Apri ${photo.name}`}
              disabled={away}
              onClick={() => setOpen(photo.id)}
            >
              <Thumb id={photo.id} />
              {away && <icons.Trash className="mark-gone" />}
            </button>
          )
        })}
      </div>
      {found.maybe.length > 0 && !unsureOnly && (
        <button type="button" className="link" onClick={() => setMore(!more)}>
          {more
            ? 'Nascondi le meno sicure'
            : found.maybe.length === 1
              ? "Mostra anche l'altra, meno sicura"
              : `Mostra anche le ${found.maybe.length} meno sicure`}
        </button>
      )}
      {/* drawn at the top of the page, outside the conversation: inside it, it would be clipped to the reply it belongs to */}
      {at >= 0 &&
        createPortal(
          <Lightbox photos={there} at={at} onMove={(to) => setOpen(there[to].id)} onClose={() => setOpen(null)} />,
          document.body,
        )}
    </div>
  )
}
