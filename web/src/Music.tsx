import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchMusic, songOf } from './api.ts'
import type { Tune } from './api.ts'
import { clock, matching } from './clock.ts'
import * as icons from './icons.tsx'

/**
 * The songs of the music folder, listened to on this computer. The same songs a paired phone plays
 * at home. The player stays when the chat is shown again: the music goes on.
 */
export default function Music({ visible }: { visible: boolean }) {
  const [folder, setFolder] = useState('')
  const [songs, setSongs] = useState<Tune[] | null>(null)
  const [problem, setProblem] = useState('')
  const [written, setWritten] = useState('')
  // the line being played, and where in it
  const [line, setLine] = useState<Tune[]>([])
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [duration, setDuration] = useState(0)
  const sound = useRef<HTMLAudioElement>(null)

  function load() {
    fetchMusic().then(
      (listed) => {
        setProblem('')
        setFolder(listed.folder)
        setSongs(listed.songs)
      },
      (error: unknown) => setProblem(error instanceof Error ? error.message : String(error)),
    )
  }

  // read each time the music is shown: songs may have been added to the folder meanwhile
  useEffect(() => {
    if (visible) load()
  }, [visible])

  const shown = useMemo(() => matching(songs ?? [], written), [songs, written])
  const now = line[index]

  // a new song in the player: it starts at once
  useEffect(() => {
    const player = sound.current
    if (!player || !now) return
    player.src = songOf(now.id)
    void player.play().catch(() => setPlaying(false))
  }, [now])

  function play(at: number) {
    // the song playing, pressed again, starts again
    if (shown[at] === now && sound.current) {
      sound.current.currentTime = 0
      void sound.current.play()
      return
    }
    setLine(shown)
    setIndex(at)
  }

  function move(step: number) {
    const player = sound.current
    // a few seconds into a song, "back" starts it again
    if (step < 0 && player && player.currentTime > 3) {
      player.currentTime = 0
      return
    }
    if (line[index + step]) setIndex(index + step)
  }

  function toggle() {
    const player = sound.current
    if (!player) return
    if (player.paused) void player.play()
    else player.pause()
  }

  return (
    <section className="music" hidden={!visible}>
      <div className="music-top">
        <div className="search">
          <icons.Search />
          <input value={written} onChange={(event) => setWritten(event.target.value)} placeholder="Cerca una canzone, un artista, un album" aria-label="Cerca una canzone" />
        </div>
        <button type="button" className="ghost small" onClick={load}>
          Leggi di nuovo
        </button>
      </div>
      {folder && <p className="fine">Le canzoni di {folder}, con le sue cartelle. Le stesse si ascoltano dal telefono, a casa.</p>}
      {problem && <p className="fine warn">Non riesco a leggere le canzoni: {problem}</p>}
      {songs?.length === 0 && <p className="fine">In questa cartella non ci sono canzoni: mettici gli MP3, o gli M4A, FLAC, OGG, WAV, e premi «Leggi di nuovo».</p>}
      {songs !== null && songs.length > 0 && written && shown.length === 0 && <p className="fine">Nessuna canzone con queste parole.</p>}

      <ul className="tunes">
        {shown.map((song, at) => (
          <li key={song.id}>
            <button type="button" className={now?.id === song.id ? 'tune on' : 'tune'} onClick={() => play(at)}>
              <icons.Note />
              <span>
                <b>{song.title}</b>
                <small>{[song.artist, song.album].filter(Boolean).join(' · ') || song.folder}</small>
              </span>
              <i className="mono">{song.kind}</i>
            </button>
          </li>
        ))}
      </ul>

      <audio
        ref={sound}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime * 1000)}
        onDurationChange={(event) => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration * 1000 : 0)}
        onEnded={() => move(1)}
      />
      {now && (
        <footer className="deck">
          <div className="now">
            <b>{now.title}</b>
            <small>{now.artist || now.folder}</small>
          </div>
          <div className="controls">
            <button type="button" className="round ghost small" aria-label="Canzone prima" onClick={() => move(-1)}>
              <icons.Previous />
            </button>
            <button type="button" className="round" aria-label={playing ? 'Pausa' : 'Suona'} onClick={toggle}>
              {playing ? <icons.Pause /> : <icons.Play />}
            </button>
            <button type="button" className="round ghost small" aria-label="Canzone dopo" disabled={!line[index + 1]} onClick={() => move(1)}>
              <icons.Next />
            </button>
          </div>
          <div className="bar">
            <span className="mono">{clock(position)}</span>
            <input
              type="range"
              min={0}
              max={duration || 1}
              value={position}
              disabled={!duration}
              onChange={(event) => {
                if (sound.current) sound.current.currentTime = Number(event.target.value) / 1000
              }}
              aria-label="Punto della canzone"
            />
            <span className="mono">{duration ? clock(duration) : ''}</span>
          </div>
        </footer>
      )}
    </section>
  )
}
