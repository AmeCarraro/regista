import { useEffect, useState } from 'react'
import { clock } from '../clock.ts'
import * as icons from '../icons.tsx'
import { connect } from './bridge.ts'
import { commandSongs } from './commandSongs.ts'

export default function CommandMusic({ title, artist }: { title: string; artist?: string }) {
  const app = connect()
  const [catalog, setCatalog] = useState(app.songs)
  const [waiting, setWaiting] = useState(false)
  const [message, setMessage] = useState('')
  const matches = commandSongs(catalog.songs, title, artist)

  useEffect(() => {
    if (!waiting) return
    const timer = setInterval(() => {
      const current = app.songs()
      if (current.allowed) {
        setCatalog(current)
        setWaiting(false)
      }
    }, 1000)
    const timeout = setTimeout(() => setWaiting(false), 20000)
    return () => {
      clearInterval(timer)
      clearTimeout(timeout)
    }
  }, [app, waiting])

  function play(id: string) {
    const current = app.songs()
    setCatalog(current)
    const song = current.allowed ? commandSongs(current.songs, title, artist).find((entry) => entry.id === id) : undefined
    if (!song) {
      setMessage('Il brano scelto non è più disponibile.')
      return
    }
    app.play([{ where: 'phone', id: song.id, title: song.title, artist: song.artist, size: song.size }], 0)
    setMessage(`Riproduzione richiesta per «${song.title}».`)
  }

  return (
    <section className="command-music" aria-label="Brani trovati sul telefono">
      {message && <p role="status">{message}</p>}
      {!catalog.allowed ? (
        <>
          <p>{waiting ? 'Attendo il permesso per la musica…' : 'Consenti l’accesso alla musica per cercare il brano sul telefono.'}</p>
          <button type="button" className="quiet" disabled={waiting} onClick={() => { setWaiting(true); app.allowSongs() }}>
            Dai il permesso per la musica
          </button>
        </>
      ) : matches.length === 0 ? (
        <p>Nessuna corrispondenza esatta nella musica del telefono.</p>
      ) : (
        <>
          <p>Scegli il brano da riprodurre.</p>
          <ul className="songs">
            {matches.map((song) => {
              const details = [song.artist, song.album, song.folder].filter(Boolean)
              return (
                <li key={song.id}>
                  <button type="button" className="song" onClick={() => play(song.id)} aria-label={['Riproduci ' + song.title, ...details].join(', ')}>
                    <icons.Play />
                    <span>
                      <b>{song.title}</b>
                      {details.length > 0 && <small>{details.join(' · ')}</small>}
                    </span>
                    {song.duration ? <i>{clock(song.duration)}</i> : null}
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}
