import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchMusic, fetchMusicLibrary, fetchMusicSync, labelSong, saveMusicPlaylist, songOf, syncMusic } from './api.ts'
import type { MusicSyncOverview, Tune } from './api.ts'
import { clock } from './clock.ts'
import * as icons from './icons.tsx'
import { MusicFilters, SongTagEditor } from './MusicCollections.tsx'
import { EMPTY_LIBRARY, musicMatches, musicSyncBusy, musicSyncText, musicTags, trackTags } from './musicLibrary.ts'

/**
 * The songs of the music folder, listened to on this computer. The same songs a paired phone plays
 * at home. The player stays when the chat is shown again: the music goes on.
 */
export default function Music({ visible, atComputer }: { visible: boolean; atComputer: boolean }) {
  const [folder, setFolder] = useState('')
  const [songs, setSongs] = useState<Tune[] | null>(null)
  const [problem, setProblem] = useState('')
  const [written, setWritten] = useState('')
  const [library, setLibrary] = useState(EMPTY_LIBRARY)
  const [tag, setTag] = useState('')
  const [playlist, setPlaylist] = useState('')
  const [editing, setEditing] = useState('')
  const [overview, setOverview] = useState<MusicSyncOverview>({ devices: [], jobs: [] })
  const [target, setTarget] = useState('')
  const [syncProblem, setSyncProblem] = useState('')
  const [requesting, setRequesting] = useState(false)
  const lastCopies = useRef('')
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

  useEffect(() => {
    if (!visible || !atComputer) return
    let active = true
    function checkSync() {
      fetchMusicSync().then((next) => {
        if (!active) return
        setOverview(next)
        const finished = next.jobs
          .filter((job) => job.sent && ['ready', 'error'].includes(job.state))
          .map((job) => job.id).sort().join(',')
        if (finished && lastCopies.current !== finished) load()
        lastCopies.current = finished
      }, () => {})
    }
    fetchMusicLibrary().then((saved) => { if (active) setLibrary(saved) }, () => {})
    checkSync()
    const timer = setInterval(checkSync, 2500)
    return () => { active = false; clearInterval(timer) }
  }, [visible, atComputer])

  const choices = useMemo(() => musicTags(songs ?? [], library), [songs, library])
  const shown = useMemo(() => musicMatches(songs ?? [], library, written, tag), [songs, library, written, tag])
  const device = overview.devices.find((phone) => phone.id === target) ?? overview.devices[0]
  const job = overview.jobs.find((item) => item.device === device?.id)
  const syncMessage = syncProblem || musicSyncText(job)
  const now = line[index]

  async function synchronize() {
    if (!device) return
    setRequesting(true)
    setSyncProblem('')
    try {
      const requested = await syncMusic(device.id)
      setOverview((before) => ({ ...before, jobs: [...before.jobs.filter((item) => item.device !== device.id), requested] }))
    } catch (error) {
      setSyncProblem(String(error instanceof Error ? error.message : error))
    } finally {
      setRequesting(false)
    }
  }

  function choosePlaylist(key: string) {
    const choice = library.playlists[key]
    setPlaylist(key)
    setTag(choice?.tag ?? '')
    setWritten(choice?.query ?? '')
  }

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
          <input value={written} maxLength={200} onChange={(event) => { setWritten(event.target.value); setPlaylist('') }} placeholder="Cerca una canzone, un artista, un album" aria-label="Cerca una canzone" />
        </div>
        <button type="button" className="ghost small" onClick={load}>
          Leggi di nuovo
        </button>
        {atComputer && (
          <>
            {overview.devices.length > 1 && (
              <select aria-label="Telefono da sincronizzare" value={device?.id ?? ''} onChange={(event) => { setTarget(event.target.value); setSyncProblem('') }}>
                {overview.devices.map((phone) => <option key={phone.id} value={phone.id}>{phone.name}</option>)}
              </select>
            )}
            <button type="button" className="library-button" disabled={!device || requesting || musicSyncBusy(job)}
              title={device ? undefined : 'Associa un telefono dalla sezione Telefono'} onClick={() => void synchronize()}>
              Sincronizza
            </button>
          </>
        )}
      </div>
      {atComputer && (
        <MusicFilters library={library} tags={choices} query={written} tag={tag} selected={playlist}
          onTag={(value) => { setTag(value); setPlaylist('') }} onPlaylist={choosePlaylist}
          onSave={async (selection) => { setLibrary(await saveMusicPlaylist(selection)) }} />
      )}
      {atComputer && syncMessage && <p className="music-feedback" role="status">{syncMessage}</p>}
      {folder && <p className="fine">Le canzoni di {folder}, con le sue cartelle. Le stesse si ascoltano dal telefono, a casa.</p>}
      {problem && <p className="fine warn">Non riesco a leggere le canzoni: {problem}</p>}
      {songs?.length === 0 && <p className="fine">In questa cartella non ci sono canzoni: mettici gli MP3, o gli M4A, FLAC, OGG, WAV, e premi «Leggi di nuovo».</p>}
      {!!songs?.length && shown.length === 0 && <p className="fine">Nessun brano corrispondente.</p>}

      <ul className="tunes">
        {shown.map((song, at) => (
          <li key={song.id}>
            <button type="button" className={now?.id === song.id ? 'tune on' : 'tune'} onClick={() => play(at)}>
              <icons.Note />
              <span>
                <b>{song.title}</b>
                <small>{[song.artist, song.album, ...trackTags(song, library)].filter(Boolean).join(' · ') || song.folder}</small>
              </span>
              <i className="mono">{song.kind}</i>
            </button>
            {atComputer && (
              <button type="button" className="library-button" aria-label={`Tag di ${song.title}`} aria-expanded={editing === song.id}
                onClick={() => setEditing(editing === song.id ? '' : song.id)}>Tag</button>
            )}
            {atComputer && editing === song.id && (
              <SongTagEditor tags={library.tags[song.id] ?? []} onClose={() => setEditing('')}
                onSave={async (tags) => { setLibrary(await labelSong(song.id, tags)) }} />
            )}
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
