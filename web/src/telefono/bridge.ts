// The page of the phone talks to the Android app around it through a few calls that the app
// offers (Phone.kt). In a browser, where there is no app, a pretend phone takes its place: so
// the page can be looked at, and tried, on the computer too.

import type { Picture } from './select.ts'
import type { Places } from './understand.ts'

/** Whether a computer was paired, which one, whether it answers now, and how many pictures wait to go to it. */
export type State = { paired: boolean; computer: string; reachable: boolean; waiting: number }

/** How far the app is in reading the day and the place of the pictures, and whether it may see them at all. */
export type Reading = { allowed: boolean; done: number; total: number }

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
}

declare global {
  interface Window {
    Regista?: Native
  }
}

export function connect(): App {
  const native = window.Regista
  if (!native) return pretend()
  const parse = <T>(text: string): T => JSON.parse(text) as T
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
  }
}

// ---- the pretend phone: three trips, and a few places

const TRIPS = [
  { country: 'JP', start: '2026-05-03', at: [35.68, 139.69], hue: 350 },
  { country: 'FR', start: '2026-06-10', at: [48.86, 2.34], hue: 220 },
  { country: 'IT', start: '2026-07-14', at: [41.89, 12.49], hue: 130 },
]

function pretend(): App {
  const pictures: Picture[] = TRIPS.flatMap((trip, number) =>
    Array.from({ length: 12 }, (_, index) => {
      const day = new Date(`${trip.start}T12:00:00Z`)
      day.setUTCDate(day.getUTCDate() + Math.floor(index / 3))
      return { id: `${number * 12 + index}`, name: `foto_${number * 12 + index}.jpg`, day: day.toISOString().slice(0, 10), lat: trip.at[0], lon: trip.at[1], country: trip.country }
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
    thumb: (id) => {
      // a colour for each trip, a shade for each picture
      const number = Number(id)
      const hue = TRIPS[Math.floor(number / 12)]?.hue ?? 280
      const picture = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><linearGradient id="g" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue + number * 7},70%,62%)"/><stop offset="1" stop-color="hsl(${hue + 40},55%,30%)"/></linearGradient></defs><rect width="10" height="10" fill="url(#g)"/></svg>`
      return `data:image/svg+xml,${encodeURIComponent(picture)}`
    },
    open: () => {},
    send: (ids) => ({ queued: ids.length }),
  }
}
