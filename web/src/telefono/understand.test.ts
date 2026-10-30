import { expect, test } from 'vitest'
import { iso } from './period.ts'
import type { Day } from './period.ts'
import { select, sentence } from './select.ts'
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
  ['le foto della Sardegna', 'IT.14', 'Sardegna', []],
  ['il mare in Emilia-Romagna', 'IT.05', 'Emilia-Romagna', ['mare']],
  ["le foto della Valle d'Aosta d'inverno", 'IT.19', "Valle d'Aosta", []],
  ['le foto del lazio', 'IT.07', 'Lazio', []],
])('a region of Italy is read from its name: %s', (text, code, name, rest) => {
  const read = understand(text, TODAY, places)
  expect(read.spot).toEqual({ kind: 'region', code, name })
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
  { id: '5', name: 'colosseo.jpg', day: '2026-07-14', lat: 41.89, lon: 12.49, country: 'IT', region: 'IT.07' },
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

test('the pictures of a region are the ones taken there, and are said with its own word', () => {
  expect(ask('le foto del Lazio').pictures.map((picture) => picture.id)).toEqual(['5'])
  expect(ask('le foto del Lazio').words).toBe('Ho trovato 1 foto scattata nel Lazio.')
  expect(ask('le foto delle Marche').words).toBe('Non ho trovato foto scattate nelle Marche tra le 6 di questo telefono.')
  expect(ask("le foto dell'estate scorsa").words).toBe('Ho trovato 4 foto da giugno ad agosto 2026.')
})

test('without a request the newest pictures are shown', () => {
  const found = ask('')

  expect(found.pictures[0].id).toBe('6')
  expect(found.words).toBe('Le foto più recenti di questo telefono.')
})

test('what the pictures should show cannot be looked for without the model, and the words say so', () => {
  expect(ask('un cane nero')).toEqual({
    pictures: [],
    words: 'Per cercare cosa mostrano le foto, come «cane nero», mi serve il modello: intanto cerco per data e per luogo, per esempio «le foto di agosto» o «le foto di Parigi».',
    sure: 0,
  })
  const narrowed = ask('le foto con un cane a Roma')
  expect(narrowed.pictures.map((picture) => picture.id)).toEqual(['5'])
  expect(narrowed.words).toBe('Ho trovato 1 foto scattata a Roma. Per cercare «cane» mi serve il modello: te la mostro.')
})

test('with the model, what the pictures show is looked for, the sure ones first and each the newest first, together with the place', () => {
  const scores = { '1': 0.34, '2': 0.29, '3': 0.31, '4': 0.1, '5': 0.27, '6': 0.25 }
  const look = (text: string) => select(pictures, understand(text, TODAY, places), scores)

  const found = look('un cane')
  // sure from 0.30, maybe from 0.26, nothing below: not the closest first, the newest
  expect(found.pictures.map((picture) => picture.id)).toEqual(['3', '1', '5', '2'])
  expect(found.sure).toBe(2)
  expect(found.words).toBe('Ho trovato 2 foto. Altre 2 potrebbero andare bene, ma ne sono meno sicuro.')
  expect(look('un cane in Giappone').words).toBe('Ho trovato 1 foto scattata in Giappone. Ce n’è un’altra che potrebbe andare bene.')
  expect(look('un cane a Roma').pictures.map((picture) => picture.id)).toEqual(['5'])
  expect(look('un cane negli Stati Uniti').words).toBe('Tra le foto scattate negli Stati Uniti non ho trovato niente del genere.')
  expect(select(pictures, understand('un cane', TODAY, places), {}).words).toBe('Non ho trovato niente del genere tra le foto che ho guardato.')
  expect(select(pictures, understand('un cane', TODAY, places), { '2': 0.27 }).words).toBe('Non sono sicuro di averne trovate. Questa è la più vicina.')
  expect(select(pictures, understand('un cane', TODAY, places), { '2': 0.25 }).words).toBe('Non ho trovato niente del genere tra le foto che ho guardato.')
})

test('the model is given what the pictures should show, as a sentence it reads best', () => {
  expect(sentence(understand('trovami le foto con un cane nero a Roma', TODAY, places).rest)).toBe('una foto di cane nero')
})
