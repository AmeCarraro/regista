// The page of the phone talks to the Android app around it through a few calls that the app
// offers (Phone.kt). In a browser, where there is no app, a pretend phone takes its place: so
// the page can be looked at, and tried, on the computer too.

import type { Picture } from './select.ts'
import type { Places } from './understand.ts'

/** Whether a computer was paired, which one, whether it answers now, and how many pictures wait to go to it. */
export type State = { paired: boolean; computer: string; reachable: boolean; waiting: number }

/** How far the app is in reading the day and the place of the pictures, and whether it may see them at all. */
export type Reading = { allowed: boolean; done: number; total: number }

/**
 * Whether the phone can see what pictures show: its own models are here (ready), or were asked
 * for (wanted) and are arriving from the computer (got of size bytes); and how many pictures it
 * has looked at, of how many.
 */
export type Sight = { ready: boolean; wanted: boolean; got: number; size: number; seen: number; unseen: number }

/** Whether the new pictures go to the computer by themselves, and when they last did: `at` in milliseconds, 0 if never. */
export type AutoCopy = { on: boolean; at: number; count: number }

/** Whether the computer has a newer app for this phone, and while it is taken, how much of it has arrived (got of size bytes). */
export type Update = { newer: boolean; taking: boolean; got: number; size: number }

/** The computer's answer to a request typed here: its words, and the pictures of this phone, by the phone's own names. */
export type Answer = { words: string; sure: string[]; maybe: string[]; model: string; seconds: number }

/** What the computer says while it looks: a picture of this phone it found, by the phone's own name; how many it has looked at, of how many. */
export type Heard = { type: 'photo'; photo: string } | { type: 'looked'; looked: number; of: number }

/** What the app hands over of the computer's answer, a few at a time: what it says on the way, and last the answer. */
type Said = Heard | { type: 'answer'; answer: Answer | null }

/** The pictures of this phone by kind, by their numbers, the sure ones apart; `unsorted` have no numbers yet. */
export type Sorted = { kinds: { kind: string; label: string; sure: string[]; maybe: string[] }[]; unsorted: number }

/** A song of this phone (its number in Android's list) or of the computer (its name there, and its file's); the phone knows how long its own are. */
export type Song = { id: string; title: string; artist: string; album: string; duration?: number; folder?: string; name?: string; kind?: string; size?: number }

/** A song in the line to play, and where it is; a song of the computer with its size, so that it plays while it arrives. */
export type Queued = { where: 'phone' | 'computer'; id: string; title: string; artist: string; size?: number }

/** What plays now: the song, where it is in its line, whether it plays or is being prepared, how far it is (milliseconds), and why not. */
export type Playing = { song: Queued | null; index: number; count: number; playing: boolean; loading: boolean; position: number; duration: number; problem: string }

export type App = {
  pictures(): Picture[]
  reading(): Reading
  state(): State
  places: Places
  /** Where the small copy of a picture is, to show it. */
  thumb(id: string): string
  /** Shows a picture in the phone's own viewer. */
  open(id: string): void
  /** Puts pictures in line to go to the computer: now if it answers, as soon as it does otherwise. */
  send(ids: string[]): { queued: number }
  sight(): Sight
  /** Asks for the models: they come from the computer as soon as it answers. */
  wantSight(): void
  /** How close each picture the phone has looked at is to a sentence; null while it has no models. */
  scores(sentence: string): Record<string, number> | null
  /**
   * Asks the computer about a request, when it answers; null when it cannot be asked, or has nothing to add.
   * `heard` is told of each picture it finds on the way, and of how far it is.
   */
  ask(text: string, heard: (event: Heard) => void): Promise<Answer | null>
  autoCopy(): AutoCopy
  /** Starts or stops the copying of the new pictures by themselves: the ones added from now on. */
  setAutoCopy(on: boolean): void
  update(): Update
  /** Takes the newer app from the computer; then Android asks the user whether to install it. */
  takeUpdate(): void
  /** The tab of the app that shows the page: "phone" for the pictures, "music" for the songs. */
  tab(): string
  /** The pictures by kind; null until the computer said once what the kinds are. The same object while nothing changed. */
  kinds(): Sorted | null
  /** Whether Android can put the music widget on the home screen when asked (from Android 8). */
  canPinWidget(): boolean
  /** Asks Android to put the music widget on the home screen: Android asks the user first. */
  pinWidget(): void
  /** The songs of this phone, and whether the app may see them. */
  songs(): { allowed: boolean; songs: Song[] }
  /** Asks Android to let the app see the songs. */
  allowSongs(): void
  /** The songs of the computer while it answers; null until it listed them. */
  computerSongs(): { reachable: boolean; songs: Song[] | null }
  /** Plays a line of songs from the one at `index`: also with the screen off. */
  play(queue: Queued[], index: number): void
  control(what: 'pause' | 'resume' | 'next' | 'previous' | 'stop'): void
  /** Jumps to a point of the song playing, in milliseconds. */
  seek(position: number): void
  player(): Playing
  /** The songs being copied and how each copy ended, by "phone:<id>" or "computer:<id>". */
  copies(): Record<string, 'copying' | 'done' | 'failed'>
  /** Copies a song of the computer onto this phone, under its file name there. */
  copyHere(id: string, name: string): void
  /** Sends a song of this phone to the computer, which keeps it in "Dal telefono". */
  copyThere(id: string): void
}

/** What the app offers the page: every answer is text, as JSON. */
type Native = {
  pictures(): string
  reading(): string
  state(): string
  country(name: string): string
  city(written: string): string
  open(id: string): void
  send(ids: string): string
  sight(): string
  wantSight(): void
  scores(sentence: string): string
  ask(text: string, token: string): void
  answer(token: string): string
  autoCopy(): string
  setAutoCopy(on: boolean): void
  update(): string
  takeUpdate(): void
  songs(): string
  allowSongs(): void
  computerSongs(): string
  play(queue: string, index: number): void
  control(what: string): void
  seek(position: number): void
  player(): string
  copies(): string
  copyHere(id: string, name: string): void
  copyThere(id: string): void
  tab(): string
  kinds(): string
  canPinWidget(): boolean
  pinWidget(): void
}

declare global {
  interface Window {
    Regista?: Native
    /** Called by the app when the computer said more about a request: what it said is taken with answer(token). */
    registaAnswered?: (token: string) => void
    /** Called by the app when one of its tabs shows this page: "phone" for the pictures, "music" for the songs. */
    registaView?: (tab: string) => void
  }
}

// how long the computer is waited for when it says nothing: its model may have to be loaded first
const PATIENCE = 45_000

type Waiting = { heard: (event: Heard) => void; done: (answer: Answer | null) => void }

let connected: App | undefined

/** The app around the page, one for all of it: the pictures and the music share it. */
export function connect(): App {
  connected ??= open()
  return connected
}

function open(): App {
  const native = window.Regista
  if (!native) return pretend()
  const parse = <T>(text: string): T => JSON.parse(text) as T
  // the requests waiting for the computer, by the name each was given
  const waiting = new Map<string, Waiting>()
  // in each name, as the app may still be telling the requests of a page shown before this one
  const page = Date.now().toString(36)
  let asked = 0
  // the kinds as the app said them last: the same answer gives the same object, and the page has nothing to redraw
  let said = ''
  let sorted: Sorted | null = null
  window.registaAnswered = (token) => {
    for (const said of parse<Said[]>(native.answer(token))) {
      const asking = waiting.get(token)
      if (said.type !== 'answer') {
        asking?.heard(said)
        continue
      }
      waiting.delete(token)
      asking?.done(said.answer)
    }
  }
  return {
    pictures: () => parse<Picture[]>(native.pictures()),
    reading: () => parse<Reading>(native.reading()),
    state: () => parse<State>(native.state()),
    places: {
      country: (name) => parse(native.country(name)),
      city: (written) => parse(native.city(written)),
    },
    thumb: (id) => `/thumb/${encodeURIComponent(id)}`,
    open: (id) => native.open(id),
    send: (ids) => parse<{ queued: number }>(native.send(JSON.stringify(ids))),
    sight: () => parse<Sight>(native.sight()),
    wantSight: () => native.wantSight(),
    scores: (sentence) => parse<Record<string, number> | null>(native.scores(sentence)),
    autoCopy: () => parse<AutoCopy>(native.autoCopy()),
    setAutoCopy: (on) => native.setAutoCopy(on),
    update: () => parse<Update>(native.update()),
    takeUpdate: () => native.takeUpdate(),
    songs: () => parse(native.songs()),
    allowSongs: () => native.allowSongs(),
    computerSongs: () => parse(native.computerSongs()),
    play: (queue, index) => native.play(JSON.stringify(queue), index),
    control: (what) => native.control(what),
    seek: (position) => native.seek(position),
    player: () => parse<Playing>(native.player()),
    copies: () => parse(native.copies()),
    copyHere: (id, name) => native.copyHere(id, name),
    copyThere: (id) => native.copyThere(id),
    tab: () => native.tab(),
    canPinWidget: () => native.canPinWidget(),
    pinWidget: () => native.pinWidget(),
    kinds: () => {
      const now = native.kinds()
      if (now !== said) {
        said = now
        sorted = parse<Sorted | null>(now)
      }
      return sorted
    },
    ask: (text, heard) =>
      new Promise((resolve) => {
        asked += 1
        const token = `a${page}${asked}`
        let patience = 0
        // the computer is waited for as long as it says something now and then
        const wait = () => {
          clearTimeout(patience)
          patience = window.setTimeout(() => {
            if (waiting.delete(token)) resolve(null)
          }, PATIENCE)
        }
        waiting.set(token, {
          heard: (event) => {
            wait()
            heard(event)
          },
          done: (answer) => {
            clearTimeout(patience)
            resolve(answer)
          },
        })
        native.ask(text, token)
        wait()
      }),
  }
}

// ---- the pretend phone: three trips, and a few places

const TRIPS = [
  { country: 'JP', start: '2026-05-03', at: [35.68, 139.69], hue: 350 },
  { country: 'FR', start: '2026-06-10', at: [48.86, 2.34], hue: 220 },
  { country: 'IT', region: 'IT.07', start: '2026-07-14', at: [41.89, 12.49], hue: 130 },
]

// the pretend phone's pictures by kind: a trip each, and the last ones of the second less sure
const ids = (from: number, to: number) => Array.from({ length: to - from }, (_, at) => String(from + at))
const KINDS: Sorted = {
  kinds: [
    { kind: 'citta', label: 'Città e monumenti', sure: ids(0, 12), maybe: [] },
    { kind: 'natura', label: 'Paesaggi e natura', sure: ids(12, 18), maybe: ids(18, 24) },
    { kind: 'persone', label: 'Persone', sure: ids(24, 36), maybe: [] },
  ],
  unsorted: 0,
}

// a few songs of the pretend phone
const SONGS: Song[] = [
  { id: '1', title: 'Azzurro', artist: 'Paolo Conte', album: 'Azzurro', duration: 183_000 },
  { id: '2', title: 'Nel blu dipinto di blu', artist: 'Domenico Modugno', album: '', duration: 214_000 },
  { id: '3', title: 'Una canzone senza nome', artist: '', album: 'Varie', duration: 95_000 },
]

function pretend(): App {
  const copying = { on: false, at: Date.UTC(2026, 9, 17, 13, 42), count: 3 }
  // what the pretend player plays: the time goes on by itself
  let playing: Playing = { song: null, index: 0, count: 0, playing: false, loading: false, position: 0, duration: 0, problem: '' }
  let line: Queued[] = []
  let started = 0
  const pictures: Picture[] = TRIPS.flatMap((trip, number) =>
    Array.from({ length: 12 }, (_, index) => {
      const day = new Date(`${trip.start}T12:00:00Z`)
      day.setUTCDate(day.getUTCDate() + Math.floor(index / 3))
      return { id: `${number * 12 + index}`, name: `foto_${number * 12 + index}.jpg`, day: day.toISOString().slice(0, 10), lat: trip.at[0], lon: trip.at[1], country: trip.country, region: trip.region }
    }),
  )
  const countries: Record<string, { code: string; name: string }> = {
    giappone: { code: 'JP', name: 'Giappone' },
    francia: { code: 'FR', name: 'Francia' },
    italia: { code: 'IT', name: 'Italia' },
  }
  const cities: Record<string, { name: string; latitude: number; longitude: number }> = {
    parigi: { name: 'Parigi', latitude: 48.85, longitude: 2.35 },
    roma: { name: 'Roma', latitude: 41.89, longitude: 12.51 },
    tokyo: { name: 'Tokyo', latitude: 35.69, longitude: 139.69 },
  }
  return {
    pictures: () => pictures,
    reading: () => ({ allowed: true, done: pictures.length, total: pictures.length }),
    state: () => ({ paired: true, computer: 'PC di casa', reachable: false, waiting: 0 }),
    places: { country: (name) => countries[name] ?? null, city: (written) => cities[written.toLowerCase()] ?? null },
    // no computer here
    ask: () => Promise.resolve(null),
    autoCopy: () => ({ ...copying }),
    setAutoCopy: (on) => {
      copying.on = on
    },
    update: () => ({ newer: false, taking: false, got: 0, size: 0 }),
    takeUpdate: () => {},
    songs: () => ({ allowed: true, songs: SONGS }),
    allowSongs: () => {},
    computerSongs: () => ({ reachable: false, songs: null }),
    play: (queue, index) => {
      playing = { ...playing, song: queue[index] ?? null, index, count: queue.length, playing: true, position: 0, duration: 200_000 }
      line = queue
      started = Date.now()
    },
    control: (what) => {
      const index = playing.index + (what === 'next' ? 1 : what === 'previous' ? -1 : 0)
      if (what === 'stop') playing = { ...playing, song: null, playing: false }
      else if (what === 'pause' || what === 'resume') playing = { ...playing, playing: what === 'resume' }
      else if (line[index]) playing = { ...playing, song: line[index], index, position: 0 }
      started = Date.now() - playing.position
    },
    seek: (position) => {
      started = Date.now() - position
    },
    player: () => (playing.playing ? { ...playing, position: Math.min(Date.now() - started, playing.duration) } : playing),
    copies: () => ({}),
    copyHere: () => {},
    copyThere: () => {},
    tab: () => (location.hash === '#musica' ? 'music' : 'phone'),
    kinds: () => KINDS,
    canPinWidget: () => true,
    pinWidget: () => {},
    thumb: (id) => {
      // a colour for each trip, a shade for each picture
      const number = Number(id)
      const hue = TRIPS[Math.floor(number / 12)]?.hue ?? 280
      const picture = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><linearGradient id="g" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue + number * 7},70%,62%)"/><stop offset="1" stop-color="hsl(${hue + 40},55%,30%)"/></linearGradient></defs><rect width="10" height="10" fill="url(#g)"/></svg>`
      return `data:image/svg+xml,${encodeURIComponent(picture)}`
    },
    open: () => {},
    send: (ids) => ({ queued: ids.length }),
    sight: () => ({ ready: false, wanted: false, got: 0, size: 0, seen: 0, unseen: pictures.length }),
    wantSight: () => {},
    scores: () => null,
  }
}
