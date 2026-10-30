import { useEffect, useMemo, useRef, useState } from 'react'
import { clock, matching } from '../clock.ts'
import * as icons from '../icons.tsx'
import { connect } from './bridge.ts'
import type { Playing, Song } from './bridge.ts'

/**
 * The songs of this phone and, at home, of the computer: played by the app, also with the screen
 * off and the app closed, with the controls on the lock screen. No computer is needed for the phone's own.
 */
export default function Musica({ visible }: { visible: boolean }) {
  const app = useMemo(() => connect(), [])
  const [where, setWhere] = useState<'phone' | 'computer'>('phone')
  const [mine, setMine] = useState(() => app.songs())
  const [theirs, setTheirs] = useState(() => app.computerSongs())
  const [playing, setPlaying] = useState<Playing>(() => app.player())
  const [written, setWritten] = useState('')
  // where the finger is on the bar while it moves: the song jumps there when it lets go
  const [scrub, setScrub] = useState<number | null>(null)
  const [link, setLink] = useState(() => app.state())
  const [copies, setCopies] = useState(() => app.copies())
  // how many songs of the computer have arrived here: at each new one the phone's list is read again
  const arrived = useRef(0)

  useEffect(() => {
    if (!visible) return
    // the songs of the phone, again each time the tab is shown: songs may have been added meanwhile
    const shownNow = setTimeout(() => setMine(app.songs()), 0)
    const timer = setInterval(() => {
      setPlaying(app.player())
      setLink(app.state())
      if (where === 'computer') setTheirs(app.computerSongs())
      // the permission may be given meanwhile: then the songs are read, once
      setMine((before) => (before.allowed ? before : app.songs()))
      const copied = app.copies()
      const here = Object.entries(copied).filter(([key, how]) => key.startsWith('computer:') && how === 'done').length
      if (here !== arrived.current) {
        arrived.current = here
        // before Android 10 the phone needs a moment to see a new song
        setMine(app.songs())
        setTimeout(() => setMine(app.songs()), 3000)
      }
      setCopies(copied)
    }, 1000)
    return () => {
      clearTimeout(shownNow)
      clearInterval(timer)
    }
  }, [visible, where, app])

  const shown = useMemo(() => matching(where === 'phone' ? mine.songs : (theirs.songs ?? []), written), [where, mine, theirs, written])
  const list = where === 'phone' ? mine.songs : (theirs.songs ?? [])
  const now = playing.song

  function play(index: number) {
    app.play(
      shown.map((song) => ({ where, id: song.id, title: song.title, artist: song.artist })),
      index,
    )
    setPlaying(app.player())
  }

  function control(what: 'pause' | 'resume' | 'next' | 'previous') {
    app.control(what)
    setPlaying(app.player())
  }

  // a song goes the other way: from the computer onto the phone, or from the phone to the computer
  const canCopy = where === 'computer' ? theirs.reachable : link.paired && link.reachable

  function copy(song: Song) {
    if (where === 'computer') app.copyHere(song.id, song.name || `${song.title}.${song.kind || 'mp3'}`)
    else app.copyThere(song.id)
    setCopies(app.copies())
  }

  return (
    <main className="phone music">
      <header className="top">
        <icons.Logo className="logo" />
        <div className="name">
          <b>Regista</b>
          <span>musica</span>
        </div>
      </header>

      <div className="sources" role="tablist">
        <button type="button" role="tab" aria-selected={where === 'phone'} onClick={() => setWhere('phone')}>
          Sul telefono
        </button>
        <button type="button" role="tab" aria-selected={where === 'computer'} onClick={() => setWhere('computer')}>
          Sul computer
        </button>
      </div>

      <form className="ask" onSubmit={(event) => event.preventDefault()}>
        <icons.Search />
        <input
          value={written}
          onChange={(event) => setWritten(event.target.value)}
          placeholder="Cerca una canzone, un artista, un album"
          aria-label="Cerca una canzone"
          enterKeyHint="search"
          autoComplete="off"
        />
      </form>

      {where === 'phone' && !mine.allowed && (
        <section className="card">
          <b>Le canzoni di questo telefono</b>
          <p>Per mostrarle e suonarle mi serve il permesso di vederle: Android te lo chiede una volta sola.</p>
          <button type="button" className="go wide" onClick={() => app.allowSongs()}>
            Dai il permesso
          </button>
        </section>
      )}
      {where === 'phone' && mine.allowed && mine.songs.length === 0 && (
        <p className="fine">Su questo telefono non trovo canzoni. Mettile nella cartella Music, oppure, a casa, ascolta quelle del computer.</p>
      )}
      {where === 'computer' && !theirs.reachable && (
        <p className="fine">Il computer non risponde: le sue canzoni si ascoltano a casa, con Regista aperto sul computer.</p>
      )}
      {where === 'computer' && theirs.reachable && theirs.songs === null && <p className="fine">Chiedo al computer le sue canzoni…</p>}
      {where === 'computer' && theirs.songs?.length === 0 && <p className="fine">Sul computer non ci sono canzoni: mettile nella sua cartella Musica.</p>}
      {list.length > 0 && written && shown.length === 0 && <p className="fine">Nessuna canzone con queste parole.</p>}

      {canCopy && shown.length > 0 && (
        <p className="fine">
          {where === 'computer' ? 'Con la freccia copi una canzone sul telefono: poi la senti anche fuori casa.' : 'Con la freccia mandi una canzone al computer, nella cartella «Dal telefono».'}
        </p>
      )}

      <ul className="songs">
        {shown.map((song, index) => {
          const copying = copies[`${where}:${song.id}`]
          return (
            <li key={song.id}>
              <button type="button" className={now?.where === where && now.id === song.id ? 'song on' : 'song'} onClick={() => play(index)}>
                <icons.Note />
                <span>
                  <b>{song.title}</b>
                  <small>{[song.artist, song.album].filter(Boolean).join(' · ') || song.folder}</small>
                </span>
                {song.duration ? <i>{clock(song.duration)}</i> : null}
              </button>
              {canCopy && (
                <button
                  type="button"
                  className={copying === 'failed' ? 'copy bad' : 'copy'}
                  disabled={copying === 'copying' || copying === 'done'}
                  aria-label={
                    copying === 'copying' ? 'La sto copiando' : copying === 'done' ? 'Copiata' : copying === 'failed' ? 'Copia non riuscita: riprova' : where === 'computer' ? 'Copia sul telefono' : 'Manda al computer'
                  }
                  onClick={() => copy(song)}
                >
                  {copying === 'copying' ? <span className="spinning" /> : copying === 'done' ? <icons.Check /> : copying === 'failed' ? <icons.Refresh /> : where === 'computer' ? <icons.Down /> : <icons.Send />}
                </button>
              )}
            </li>
          )
        })}
      </ul>

      {now && (
        <footer className="player">
          <div className="now">
            <b>{now.title}</b>
            <small className={playing.problem ? 'bad' : ''}>
              {playing.problem || (playing.loading ? (now.where === 'computer' ? 'La prendo dal computer…' : 'Un attimo…') : now.artist)}
            </small>
          </div>
          <input
            type="range"
            min={0}
            max={playing.duration || 1}
            value={scrub ?? playing.position}
            disabled={playing.loading || !playing.duration}
            onChange={(event) => setScrub(Number(event.target.value))}
            onPointerUp={() => {
              if (scrub !== null) app.seek(scrub)
              setScrub(null)
            }}
            aria-label="Punto della canzone"
          />
          <div className="times">
            <span>{clock(scrub ?? playing.position)}</span>
            <span>{playing.duration ? clock(playing.duration) : ''}</span>
          </div>
          <div className="controls">
            <button type="button" className="round" aria-label="Canzone prima" onClick={() => control('previous')}>
              <icons.Previous />
            </button>
            <button type="button" className="go round big" aria-label={playing.playing ? 'Pausa' : 'Suona'} onClick={() => control(playing.playing ? 'pause' : 'resume')}>
              {playing.playing ? <icons.Pause /> : <icons.Play />}
            </button>
            <button type="button" className="round" aria-label="Canzone dopo" disabled={playing.index >= playing.count - 1} onClick={() => control('next')}>
              <icons.Next />
            </button>
          </div>
        </footer>
      )}
    </main>
  )
}
