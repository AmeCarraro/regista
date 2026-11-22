import { useEffect, useMemo, useRef, useState } from 'react'
import { clock, matching } from '../clock.ts'
import * as icons from '../icons.tsx'
import { MusicFilters, SongTagEditor } from '../MusicCollections.tsx'
import { EMPTY_LIBRARY, musicMatches, musicSyncBusy, musicSyncText, musicTags, trackTags } from '../musicLibrary.ts'
import { addedInWords } from './added.ts'
import { connect } from './bridge.ts'
import type { Playing, Song } from './bridge.ts'

/**
 * The songs of this phone and, at home, of the computer: played by the app, also with the screen
 * off and the app closed, with the controls on the lock screen. No computer is needed for the phone's own.
 * Songs elsewhere on the phone, as the ones received on WhatsApp, are added by copying them into its music.
 */
export default function Musica({ visible }: { visible: boolean }) {
  const app = useMemo(() => connect(), [])
  const [where, setWhere] = useState<'phone' | 'computer'>('phone')
  const [mine, setMine] = useState(() => app.songs())
  const [theirs, setTheirs] = useState(() => app.computerSongs())
  const [playing, setPlaying] = useState<Playing>(() => app.player())
  const [written, setWritten] = useState('')
  const [library, setLibrary] = useState(() => app.musicCollections())
  const [tag, setTag] = useState('')
  const [playlist, setPlaylist] = useState('')
  const [editing, setEditing] = useState('')
  const [sync, setSync] = useState(() => app.musicSyncState())
  const synced = useRef('')
  // where the finger is on the bar while it moves: the song jumps there when it lets go
  const [scrub, setScrub] = useState<number | null>(null)
  const [link, setLink] = useState(() => app.state())
  const [copies, setCopies] = useState(() => app.copies())
  const [adding, setAdding] = useState(() => app.added())
  // how many songs of the computer have arrived here: at each new one the phone's list is read again
  const arrived = useRef(0)
  // how the adding of songs went, as last told: at each change the phone's list is read again too
  const told = useRef('')

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
      const currentSync = app.musicSyncState()
      setSync(currentSync)
      if (currentSync.id && currentSync.received && !musicSyncBusy(currentSync) && currentSync.id !== synced.current) {
        synced.current = currentSync.id
        setMine(app.songs())
        setTimeout(() => setMine(app.songs()), 3000)
      }
      const now = app.added()
      const said = JSON.stringify(now)
      if (said !== told.current) {
        told.current = said
        setAdding(now)
        setMine(app.songs())
        setTimeout(() => setMine(app.songs()), 3000)
      }
    }, 1000)
    return () => {
      clearTimeout(shownNow)
      clearInterval(timer)
    }
  }, [visible, where, app])

  const choices = useMemo(() => musicTags(mine.songs, library), [mine.songs, library])
  const labels = where === 'phone' ? library : EMPTY_LIBRARY
  const shown = useMemo(() => where === 'phone'
    ? musicMatches(mine.songs, library, written, tag)
    : matching(theirs.songs ?? [], written), [where, mine, theirs, written, library, tag])
  const list = where === 'phone' ? mine.songs : (theirs.songs ?? [])
  const synchronizing = musicSyncBusy(sync)
  const syncMessage = musicSyncText(sync)
  const addingMessage = adding.total > 0 ? addedInWords(adding) : ''
  const now = playing.song

  function play(index: number) {
    app.play(
      shown.map((song) => ({ where, id: song.id, title: song.title, artist: song.artist, size: song.size })),
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

  function choosePlaylist(key: string) {
    const choice = library.playlists[key]
    setPlaylist(key)
    setTag(choice?.tag ?? '')
    setWritten(choice?.query ?? '')
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
          maxLength={200}
          onChange={(event) => { setWritten(event.target.value); setPlaylist('') }}
          placeholder="Cerca una canzone, un artista, un album"
          aria-label="Cerca una canzone"
          enterKeyHint="search"
          autoComplete="off"
        />
      </form>

      <div className="music-filters music-actions">
        {where === 'phone' && mine.allowed && (
          <button type="button" className="library-button" disabled={adding.busy || synchronizing} onClick={() => app.addSongs()}>Aggiungi canzoni</button>
        )}
        <button type="button" className="library-button" disabled={synchronizing || adding.busy || !link.reachable}
          title={link.reachable ? undefined : 'Collega Regista al computer'} onClick={() => app.syncMusic()}>
          Sincronizza
        </button>
        {where === 'phone' && addingMessage && <small className="music-feedback" role="status">{addingMessage}</small>}
        {syncMessage && <small className="music-feedback" role="status">{syncMessage}</small>}
      </div>

      {where === 'phone' && mine.allowed && (
        <MusicFilters library={library} tags={choices} query={written} tag={tag} selected={playlist}
          onTag={(value) => { setTag(value); setPlaylist('') }} onPlaylist={choosePlaylist}
          onSave={async (selection) => { setLibrary(app.saveMusicPlaylist(selection)) }} />
      )}

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
        <p className="fine">Su questo telefono non trovo canzoni. Aggiungile con il tasto qui sopra, anche quelle arrivate su WhatsApp, oppure, a casa, ascolta quelle del computer.</p>
      )}
      {where === 'computer' && !theirs.reachable && (
        <p className="fine">Il computer non risponde: le sue canzoni si ascoltano a casa, con Regista aperto sul computer.</p>
      )}
      {where === 'computer' && theirs.reachable && theirs.songs === null && <p className="fine">Chiedo al computer le sue canzoni…</p>}
      {where === 'computer' && theirs.songs?.length === 0 && <p className="fine">Sul computer non ci sono canzoni: mettile nella sua cartella Musica.</p>}
      {list.length > 0 && shown.length === 0 && <p className="fine">Nessun brano corrispondente.</p>}

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
                  <small>{[song.artist, song.album, ...trackTags(song, labels)].filter(Boolean).join(' · ') || song.folder}</small>
                </span>
                {song.duration ? <i>{clock(song.duration)}</i> : null}
              </button>
              {where === 'phone' && (
                <button type="button" className="library-button" aria-label={`Tag di ${song.title}`} aria-expanded={editing === song.id}
                  onClick={() => setEditing(editing === song.id ? '' : song.id)}>Tag</button>
              )}
              {canCopy && (
                <button
                  type="button"
                  className={copying === 'failed' ? 'copy bad' : 'copy'}
                  disabled={synchronizing || copying === 'copying' || copying === 'done'}
                  aria-label={
                    copying === 'copying' ? 'La sto copiando' : copying === 'done' ? 'Copiata' : copying === 'failed' ? 'Copia non riuscita: riprova' : where === 'computer' ? 'Copia sul telefono' : 'Manda al computer'
                  }
                  onClick={() => copy(song)}
                >
                  {copying === 'copying' ? <span className="spinning" /> : copying === 'done' ? <icons.Check /> : copying === 'failed' ? <icons.Refresh /> : where === 'computer' ? <icons.Down /> : <icons.Send />}
                </button>
              )}
              {where === 'phone' && editing === song.id && (
                <SongTagEditor tags={library.tags[song.id] ?? []} onClose={() => setEditing('')}
                  onSave={async (tags) => { setLibrary(app.labelSong(song.id, tags)) }} />
              )}
            </li>
          )
        })}
      </ul>

      {where === 'phone' && mine.allowed && (
        <p className="fine widget-hint">
          {app.canPinWidget() ? (
            <button type="button" className="link" onClick={() => app.pinWidget()}>
              Metti la musica nella schermata Home
            </button>
          ) : (
            'Per avere la musica nella schermata Home: tieni premuto su uno spazio vuoto della schermata Home, scegli «Widget» e poi «Regista».'
          )}
        </p>
      )}

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
