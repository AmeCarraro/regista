import { useEffect, useMemo, useState } from 'react'
import './bridge.ts'

type VideoState = { videos: { id: string; title: string }[]; adding: boolean; error: string }
function current(): VideoState {
  try { return JSON.parse(window.Regista?.videos?.() || '{"videos":[],"adding":false,"error":""}') as VideoState }
  catch { return { videos: [], adding: false, error: 'Raccolta video non disponibile.' } }
}

export default function Video({ visible }: { visible: boolean }) {
  const [state, setState] = useState(current)
  const [query, setQuery] = useState('')
  useEffect(() => {
    if (!visible) return
    const timer = setInterval(() => setState(current()), 1000)
    return () => clearInterval(timer)
  }, [visible])
  const shown = useMemo(() => {
    const words = query.toLocaleLowerCase('it-IT').split(/\s+/).filter(Boolean)
    return state.videos.filter(video => words.every(word => video.title.toLocaleLowerCase('it-IT').includes(word)))
  }, [state.videos, query])
  if (!visible) return null
  return <main className="phone videos">
    <h1>Video del telefono</h1>
    <p>Scegli i video dalle tue cartelle e guardali in Regista. Restano dove sono, senza copiarli sul PC.</p>
    <button disabled={state.adding} onClick={() => window.Regista?.addVideos?.()}>{state.adding ? 'Aggiungo i video…' : 'Scegli video dal telefono'}</button>
    {state.error && <p role="alert">{state.error}</p>}
    <label>Cerca un video<input value={query} placeholder="Nome del video" onChange={event => setQuery(event.target.value)} /></label>
    {!shown.length && <p>{state.videos.length ? 'Nessun video con questo nome.' : 'Non hai ancora scelto video.'}</p>}
    <ul className="video-list">{shown.map(video => <li key={video.id}>
      <button onClick={() => window.Regista?.playVideo?.(video.id)}>Riproduci · {video.title}</button>
      <button disabled={state.adding} aria-label={`Togli ${video.title} dalla raccolta`} onClick={() => { window.Regista?.removeVideo?.(video.id); setState(current()) }}>Togli dalla raccolta</button>
    </li>)}</ul>
    <p>Il lettore usa i formati supportati dal telefono. Togliere un video dalla raccolta lascia intatto il file originale.</p>
  </main>
}
