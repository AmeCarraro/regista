import { expect, test } from 'vitest'
import { iso } from './period.ts'
import type { Day } from './period.ts'
import { select } from './select.ts'
import type { Picture } from './select.ts'
import { understand } from './understand.ts'
import type { Places } from './understand.ts'

const TODAY: Day = { year: 2026, month: 10, day: 12 }
const PARIS = { latitude: 48.8534, longitude: 2.3488 }
const ROME = { latitude: 41.8919, longitude: 12.5113 }

/** A few places in place of the phone's table: the names as Places.kt gives them back. */
const places: Places = {
  country: (name) =>
    ({
      giappone: { code: 'JP', name: 'Giappone' },
      japan: { code: 'JP', name: 'Giappone' },
      italia: { code: 'IT', name: 'Italia' },
      'stati uniti': { code: 'US', name: 'Stati Uniti' },
      "costa d'avorio": { code: 'CI', name: "Costa d'Avorio" },
    })[name] ?? null,
  city: (written) => {
    const known: Record<string, { latitude: number; longitude: number }> = { parigi: PARIS, roma: ROME, 'new york': { latitude: 40.71, longitude: -74.0 } }
    const found = known[written.toLowerCase()]
    // as the table does: a name in small letters only for a large city, and Roma and Parigi are
    return found ? { name: written.charAt(0).toUpperCase() + written.slice(1), ...found } : null
  },
}

test.each([
  ['le foto del Giappone', 'JP', []],
  ["foto dell'Italia di agosto", 'IT', []],
  ['le foto degli Stati Uniti', 'US', []],
  ["foto della Costa d'Avorio", 'CI', []],
  ['Japan', 'JP', []],
  // in small letters too: a country is a country however it is written
  ['le foto del giappone', 'JP', []],
])('a country is read from its name: %s', (text, code, rest) => {
  const read = understand(text, TODAY, places)
  expect(read.spot).toMatchObject({ kind: 'country', code })
  expect(read.rest).toEqual(rest)
})

test.each([
  ['le foto di Parigi', 'Parigi', []],
  ['trovami le foto con un cane a Roma', 'Roma', ['cane']],
  ['le foto di New York di agosto 2024', 'New York', []],
  ['Parigi di notte', 'Parigi', ['notte']],
])('a city is read from its name, and what else the request says is kept: %s', (text, name, rest) => {
  const read = understand(text, TODAY, places)
  expect(read.spot).toMatchObject({ kind: 'city', name })
  expect(read.rest).toEqual(rest)
})

test.each([
  ['le foto del mare', ['mare']],
  ['un cane nero', ['cane', 'nero']],
  ['le foto di Natale', ['natale']],
  ['Mare di notte', ['mare', 'notte']],
])('a word that a picture shows is not a place: %s', (text, rest) => {
  const read = understand(text, TODAY, places)
  expect(read.spot).toBeNull()
  expect(read.rest).toEqual(rest)
})

test('a period and a place are read together, and the words of the period are not something to look for', () => {
  const read = understand('le foto di Parigi dal 10 al 14 giugno', TODAY, places)

  expect(read.period?.map(iso)).toEqual(['2026-06-10', '2026-06-14'])
  expect(read.spot).toMatchObject({ kind: 'city', name: 'Parigi' })
  expect(read.rest).toEqual([])
})

// ---- choosing the pictures

const pictures: Picture[] = [
  { id: '1', name: 'tokyo.jpg', day: '2026-05-03', lat: 35.68, lon: 139.69, country: 'JP' },
  { id: '2', name: 'kyoto.jpg', day: '2026-05-05', lat: 35.01, lon: 135.76, country: 'JP' },
  { id: '3', name: 'louvre.jpg', day: '2026-06-11', lat: 48.86, lon: 2.34, country: 'FR' },
  { id: '4', name: 'versailles.jpg', day: '2026-06-12', lat: 48.8, lon: 2.12, country: 'FR' },
  { id: '5', name: 'colosseo.jpg', day: '2026-07-14', lat: 41.89, lon: 12.49, country: 'IT' },
  { id: '6', name: 'screenshot.png', day: '2026-07-20' },
]
const ask = (text: string) => select(pictures, understand(text, TODAY, places))

test('the pictures of a country, of a city and of a period are chosen and said', () => {
  expect(ask('le foto del Giappone').pictures.map((picture) => picture.id)).toEqual(['2', '1'])
  expect(ask('le foto del Giappone').words).toBe('Ho trovato 2 foto scattate in Giappone.')
  // within 50 km of the city: Versailles is Paris too
  expect(ask('le foto di Parigi').pictures.map((picture) => picture.id)).toEqual(['4', '3'])
  expect(ask('le foto di Parigi del 12 giugno').words).toBe('Ho trovato 1 foto scattata a Parigi del 12 giugno 2026.')
  expect(ask('le foto di luglio').pictures.map((picture) => picture.id)).toEqual(['6', '5'])
  expect(ask('le foto degli Stati Uniti').words).toBe('Non ho trovato foto scattate negli Stati Uniti tra le 6 di questo telefono.')
})

test('without a request the newest pictures are shown', () => {
  const found = ask('')

  expect(found.pictures[0].id).toBe('6')
  expect(found.words).toBe('Le foto più recenti di questo telefono.')
})

test('what the pictures should show cannot be looked for without the computer, and the words say so', () => {
  expect(ask('un cane nero')).toEqual({
    pictures: [],
    words: 'Senza il computer, per ora cerco per data e per luogo: per esempio «le foto di agosto» o «le foto di Parigi». Per cercare «cane nero» usa la scheda Computer.',
  })
  const narrowed = ask('le foto con un cane a Roma')
  expect(narrowed.pictures.map((picture) => picture.id)).toEqual(['5'])
  expect(narrowed.words).toBe('Ho trovato 1 foto scattata a Roma. Senza il computer non so ancora cercare «cane»: te la mostro.')
})
