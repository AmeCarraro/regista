// The pictures of the phone that a request asks for, and what is said about them: chosen on
// the phone, from what the app knows of each picture (the day and the place it was taken).

import { inWords, iso } from './period.ts'
import { REGIONS } from './regions.ts'
import type { Spot, Understood } from './understand.ts'

/** A picture of the phone, as the app knows it: `country` and `region` are the codes of where it was taken, "IT" and "IT.14". */
export type Picture = { id: string; name: string; day: string; lat?: number | null; lon?: number | null; country?: string; region?: string }

/** The pictures chosen, the sure ones first: `sure` says how many of them are. */
export type Found = { pictures: Picture[]; words: string; sure: number }

// how far from a city a picture can be and still be "of" that city, in kilometres: as on the computer
const NEAR = 50
// How close to a sentence a picture must be to be shown as sure, and as maybe. Measured on 200
// pictures of ten kinds with twenty requests in Italian: above 0.26 nine in ten are right, above 0.24 two in three.
export const SURE = 0.26
export const MAYBE = 0.24

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

/** A place after "scattate": "a Parigi", "in Giappone", "nel Lazio". */
export function at(spot: Spot): string {
  if (spot.kind === 'city') return `a ${spot.name}`
  if (spot.kind === 'region') return REGIONS[spot.code].at
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
  if (spot.kind === 'region') return picture.region === spot.code
  return picture.lat != null && picture.lon != null && distance(spot.latitude, spot.longitude, picture.lat, picture.lon) <= NEAR
}

const count = (number: number) => (number === 1 ? '1 foto' : `${number} foto`)

/** The newest first; on the same day, by name. */
function newestFirst(pictures: Picture[]): Picture[] {
  return [...pictures].sort((one, other) => other.day.localeCompare(one.day) || one.name.localeCompare(other.name))
}

/** The sentence the phone's model is given for what a request says the pictures show: so it finds them best. */
export function sentence(rest: string[]): string {
  return `una foto di ${rest.join(' ')}`
}

/**
 * The pictures a request asks for, and the words that say what was found. `scores` is how close
 * each picture is to what the request says the pictures show, when the phone can see that; null
 * when it cannot, and then the words say so.
 */
export function select(pictures: Picture[], understood: Understood, scores: Record<string, number> | null = null): Found {
  const { period, spot, rest } = understood
  const what = rest.join(' ')
  const looking = rest.length > 0
  if (!period && !spot && !looking) {
    return { pictures: newestFirst(pictures), words: pictures.length ? 'Le foto più recenti di questo telefono.' : 'Su questo telefono non trovo foto.', sure: 0 }
  }
  if (!period && !spot && !scores) {
    return {
      pictures: [],
      words: `Per cercare cosa mostrano le foto, come «${what}», mi serve il modello: intanto cerco per data e per luogo, per esempio «le foto di agosto» o «le foto di Parigi».`,
      sure: 0,
    }
  }
  const [since, until] = period ? period.map(iso) : ['', '']
  const chosen = pictures.filter((picture) => (!period || (picture.day >= since && picture.day <= until)) && (!spot || inside(picture, spot)))
  // "1 foto scattata", "2 foto scattate"
  const told = (number: number) => (spot ? ` scattat${number === 1 ? 'a' : 'e'} ${at(spot)}` : '') + (period ? ` ${inWords(period)}` : '')
  if (looking && scores) {
    const scored = chosen.filter((picture) => (scores[picture.id] ?? 0) >= MAYBE).sort((one, other) => scores[other.id] - scores[one.id])
    const sure = scored.filter((picture) => scores[picture.id] >= SURE).length
    const maybe = scored.length - sure
    let words: string
    if (sure) {
      words = `Ho trovato ${count(sure)}${told(sure)}.`
      if (maybe) words += maybe === 1 ? ' Ce n’è un’altra che potrebbe andare bene.' : ` Altre ${maybe} potrebbero andare bene, ma ne sono meno sicuro.`
    } else {
      // "Tra le foto scattate a Roma non ho trovato…": the place and the period first, when the request names them
      const among = spot || period ? `Tra le foto${told(2)} ` : ''
      const nearest = maybe === 1 ? 'Questa è la più vicina.' : `Queste ${maybe} sono le più vicine.`
      words = maybe
        ? `${among}${among ? 'non' : 'Non'} sono sicuro di averne trovate. ${nearest}`
        : `${among}${among ? 'non' : 'Non'} ho trovato niente del genere${among ? '' : ' tra le foto che ho guardato'}.`
    }
    return { pictures: scored, words, sure }
  }
  if (chosen.length === 0) return { pictures: [], words: `Non ho trovato foto${told(0)} tra le ${pictures.length} di questo telefono.`, sure: 0 }
  let words = `Ho trovato ${count(chosen.length)}${told(chosen.length)}.`
  if (looking) words += ` Per cercare «${what}» mi serve il modello: ${chosen.length === 1 ? 'te la mostro' : 'te le mostro tutte'}.`
  return { pictures: newestFirst(chosen), words, sure: chosen.length }
}
