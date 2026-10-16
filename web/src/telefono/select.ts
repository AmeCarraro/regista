// The pictures of the phone that a request asks for, and what is said about them: chosen on
// the phone, from what the app knows of each picture (the day and the place it was taken).

import { inWords, iso } from './period.ts'
import type { Spot, Understood } from './understand.ts'

/** A picture of the phone, as the app knows it. `country` is the code of the country it was taken in. */
export type Picture = { id: string; name: string; day: string; lat?: number | null; lon?: number | null; country?: string }

export type Found = { pictures: Picture[]; words: string }

// how far from a city a picture can be and still be "of" that city, in kilometres: as on the computer
const NEAR = 50

// countries whose names are said with another word than "in": "negli Stati Uniti", "nel Regno Unito"
const IN_COUNTRY: Record<string, string> = {
  US: 'negli Stati Uniti',
  GB: 'nel Regno Unito',
  NL: 'nei Paesi Bassi',
  AE: 'negli Emirati Arabi Uniti',
  PH: 'nelle Filippine',
  MV: 'nelle Maldive',
  SC: 'nelle Seychelles',
  VA: 'nella Città del Vaticano',
}

/** A place after "scattate": "a Parigi", "in Giappone". */
export function at(spot: Spot): string {
  if (spot.kind === 'city') return `a ${spot.name}`
  return IN_COUNTRY[spot.code] ?? `in ${spot.name}`
}

/** Kilometres between two points given in degrees, along the surface of the Earth. */
function distance(latitude1: number, longitude1: number, latitude2: number, longitude2: number): number {
  const radians = (degrees: number) => (degrees * Math.PI) / 180
  const half = Math.sin(radians(latitude2 - latitude1) / 2) ** 2 + Math.cos(radians(latitude1)) * Math.cos(radians(latitude2)) * Math.sin(radians(longitude2 - longitude1) / 2) ** 2
  return 2 * 6371 * Math.asin(Math.sqrt(half))
}

function inside(picture: Picture, spot: Spot): boolean {
  if (spot.kind === 'country') return picture.country === spot.code
  return picture.lat != null && picture.lon != null && distance(spot.latitude, spot.longitude, picture.lat, picture.lon) <= NEAR
}

const count = (number: number) => (number === 1 ? '1 foto' : `${number} foto`)

/** The newest first; on the same day, by name. */
function newestFirst(pictures: Picture[]): Picture[] {
  return [...pictures].sort((one, other) => other.day.localeCompare(one.day) || one.name.localeCompare(other.name))
}

/**
 * The pictures a request asks for, and the words that say what was found. `looks` says whether
 * the phone can see what pictures show: without it, what the request says beyond the day and the
 * place cannot be looked for, and the words say so.
 */
export function select(pictures: Picture[], understood: Understood, looks = false): Found {
  const { period, spot, rest } = understood
  const what = rest.join(' ')
  if (!period && !spot) {
    if (rest.length > 0 && !looks) {
      return {
        pictures: [],
        words: `Senza il computer, per ora cerco per data e per luogo: per esempio «le foto di agosto» o «le foto di Parigi». Per cercare «${what}» usa la scheda Computer.`,
      }
    }
    return { pictures: newestFirst(pictures), words: pictures.length ? 'Le foto più recenti di questo telefono.' : 'Su questo telefono non trovo foto.' }
  }
  const [since, until] = period ? period.map(iso) : ['', '']
  const chosen = pictures.filter((picture) => (!period || (picture.day >= since && picture.day <= until)) && (!spot || inside(picture, spot)))
  // "1 foto scattata", "2 foto scattate"
  const told = (number: number) => (spot ? ` scattat${number === 1 ? 'a' : 'e'} ${at(spot)}` : '') + (period ? ` ${inWords(period)}` : '')
  if (chosen.length === 0) return { pictures: [], words: `Non ho trovato foto${told(0)} tra le ${pictures.length} di questo telefono.` }
  let words = `Ho trovato ${count(chosen.length)}${told(chosen.length)}.`
  if (rest.length > 0 && !looks) words += ` Senza il computer non so ancora cercare «${what}»: ${chosen.length === 1 ? 'te la mostro' : 'te le mostro tutte'}.`
  return { pictures: newestFirst(chosen), words }
}
