import { useEffect, useMemo, useState } from 'react'
import './bridge.ts'
import PhoneHeader from './PhoneHeader.tsx'
import { Cross, Play, Plus, Search } from '../icons.tsx'

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
    <PhoneHeader section="video" />
    <div className="phone-intro"><h1>I tuoi video</h1><p>Un momento da riguardare, anche senza PC.</p></div>
    <button className="phone-action primary" disabled={state.adding} onClick={() => window.Regista?.addVideos?.()}><Plus />{state.adding ? 'Aggiungo i video…' : 'Scegli video dal telefono'}</button>
    {state.error && <p className="phone-feedback" role="alert">{state.error}</p>}
    <label className="ask saved-search"><Search /><input aria-label="Cerca un video" value={query} placeholder="Cerca un video" enterKeyHint="search" onChange={event => setQuery(event.target.value)} /></label>
    {!shown.length && <div className="phone-empty"><span className="phone-empty-icon"><Play /></span><h2>{state.videos.length ? 'Nessun video trovato' : 'La tua sala, sul telefono'}</h2>
      <p>{state.videos.length ? 'Prova a cercare con un altro nome.' : 'Aggiungi un video dalle tue cartelle e guardalo qui. Il file resta dove si trova.'}</p></div>}
    <ul className="video-list">{shown.map(video => <li key={video.id}>
      <button className="video-play" onClick={() => window.Regista?.playVideo?.(video.id)} aria-label={`Riproduci ${video.title}`}><span className="video-play-icon"><Play /></span><span><b>{video.title}</b><small>Sul telefono</small></span></button>
      <button className="phone-icon" disabled={state.adding} aria-label={`Togli ${video.title} dalla raccolta`} onClick={() => { window.Regista?.removeVideo?.(video.id); setState(current()) }}><Cross /></button>
    </li>)}</ul>
    <p className="phone-caption">Togliere un video dalla raccolta lascia intatto il file originale. Il lettore usa i formati supportati dal telefono.</p>
  </main>
}
