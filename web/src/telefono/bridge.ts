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

/** The computer's answer to a request typed here: its words, and the pictures of this phone, by the phone's own names. */
export type Answer = { words: string; sure: string[]; maybe: string[]; model: string; seconds: number }

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
  /** Asks the computer about a request, when it answers; null when it cannot be asked, or has nothing to add. */
  ask(text: string): Promise<Answer | null>
  autoCopy(): AutoCopy
  /** Starts or stops the copying of the new pictures by themselves: the ones added from now on. */
  setAutoCopy(on: boolean): void
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
}

declare global {
  interface Window {
    Regista?: Native
    /** Called by the app when the computer's answer to a request is there. */
    registaAnswered?: (token: string) => void
  }
}

// how long the computer is waited for: its model may have to be loaded first
const PATIENCE = 45_000

export function connect(): App {
  const native = window.Regista
  if (!native) return pretend()
  const parse = <T>(text: string): T => JSON.parse(text) as T
  // the requests waiting for the computer, by the name each was given
  const waiting = new Map<string, (answer: Answer | null) => void>()
  let asked = 0
  window.registaAnswered = (token) => {
    const done = waiting.get(token)
    waiting.delete(token)
    done?.(parse<Answer | null>(native.answer(token)))
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
    ask: (text) =>
      new Promise((resolve) => {
        asked += 1
        const token = `a${asked}`
        waiting.set(token, resolve)
        native.ask(text, token)
        setTimeout(() => {
          if (waiting.delete(token)) resolve(null)
        }, PATIENCE)
      }),
  }
}

// ---- the pretend phone: three trips, and a few places

const TRIPS = [
  { country: 'JP', start: '2026-05-03', at: [35.68, 139.69], hue: 350 },
  { country: 'FR', start: '2026-06-10', at: [48.86, 2.34], hue: 220 },
  { country: 'IT', region: 'IT.07', start: '2026-07-14', at: [41.89, 12.49], hue: 130 },
]

function pretend(): App {
  const copying = { on: false, at: Date.UTC(2026, 9, 17, 13, 42), count: 3 }
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
