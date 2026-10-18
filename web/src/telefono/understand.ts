// What a request typed on the phone asks for, read on the phone itself, with no model: when the
// pictures were taken (period.ts), where (the countries by their names, the regions of Italy, the
// cities of a table the app carries), and what else it says, which is what the pictures should show.

import { MONTHS, SEASON_NAMES, read } from './period.ts'
import type { Day, Period } from './period.ts'
import { REGIONS, REGION_NAMED } from './regions.ts'

/** Where pictures were taken, as a request names it. */
export type Spot =
  | { kind: 'country'; code: string; name: string }
  | { kind: 'region'; code: string; name: string }
  | { kind: 'city'; name: string; latitude: number; longitude: number }

/** What the phone knows of places (Places.kt): countries by their names, and the cities of a table. */
export type Places = {
  /** The country a name is of, in Italian or in English, given in small letters: "giappone", "stati uniti". */
  country(name: string): { code: string; name: string } | null
  /**
   * The city a name is of, as the user wrote it. A name written in small letters is taken only
   * for a large city: many small towns have names that are also words.
   */
  city(written: string): { name: string; latitude: number; longitude: number } | null
}

export type Understood = {
  period: Period | null
  spot: Spot | null
  /** What else the request says, in its own words and in small letters: what the pictures should show. */
  rest: string[]
}

// the words around what a request wants, which say nothing of the pictures
const FILLER = new Set(
  (
    'foto fotografie fotografia immagini immagine scatti scatto trovami trova trovare cerca cercami cercare mostrami mostra ' +
    'fammi fai vedere vedi dammi voglio vorrei tutte tutti tutta tutto mie miei mia mio ho hai fatto fatte fatta ' +
    'scattate scattata scattato scattati fotografato fotografata sul telefono tablet cellulare qui qua per favore grazie ciao ' +
    'ora adesso solo soltanto anche che cosa quali quale quelle quella quelli quello queste questa questi questo dove ' +
    'il lo la i gli le l un uno una di del dello della dei degli delle dell d a ad al allo alla ai agli alle all ' +
    'da dal dallo dalla dai dagli dalle dall in nel nello nella nei negli nelle nell con col su sullo sulla sui sugli ' +
    'sulle sull tra fra e ed o oppure non mi ti ci vi si me te'
  ).split(' '),
)
// the words of a period, which period.ts has read already
const TIME = new Set([
  ...MONTHS,
  ...SEASON_NAMES,
  ...'oggi ieri altro altroieri settimana scorsa scorso passata passato mese anno quest ultimi ultime giorni giorno settimane mesi anni'.split(' '),
])
// words that join the parts of the name of a place: "Città del Vaticano", "Rio de Janeiro", "Costa d'Avorio"
const JOINS = new Set(['del', 'della', 'de', 'di', 'da', 'do', 'dos', 'das', 'la', 'las', 'los', 'el', 'e', 'y', 'sur', 'd', 'upon'])
// words a picture often shows, and that are also the names of towns somewhere: never read as places
const SUBJECTS = new Set(
  (
    'mare sole sale casa lago pace neve monte monti natale pasqua festa feste sera notte alba tramonto spiaggia montagna ' +
    'città campagna cane cani gatto gatti fiore fiori albero alberi chiesa chiese ponte porto torre piazza strada bosco ' +
    'isola fiume cielo luna stelle bambini amici famiglia matrimonio compleanno cena pranzo vacanza vacanze viaggio'
  ).split(' '),
)

type Word = { written: string; small: string; elided: boolean }

/** The words of a request, in order: "dell'Italia" is two, "dell'" and "Italia". */
function words(text: string): Word[] {
  return [...text.matchAll(/\p{L}+['’]|[\p{L}\p{N}]+/gu)].map(([written]) => {
    const elided = /['’]$/.test(written)
    const bare = elided ? written.slice(0, -1) : written
    return { written: bare, small: bare.toLowerCase(), elided }
  })
}

/** A name as it is written: "Costa d'Avorio", "New York". */
function named(parts: Word[]): string {
  return parts.map((part, at) => (part.elided ? `${part.written}'` : part.written + (at < parts.length - 1 ? ' ' : ''))).join('').trim()
}

const isNumber = (word: Word) => /^\p{N}+$/u.test(word.written)

/**
 * The place a request names, and where its words are. The longest name wins, then the first:
 * "Stati Uniti" before "Uniti", "Città del Vaticano" before "Vaticano".
 */
function place(found: Word[], places: Places): { spot: Spot; from: number; to: number } | null {
  for (let size = Math.min(4, found.length); size >= 1; size--) {
    for (let from = 0; from + size <= found.length; from++) {
      const parts = found.slice(from, from + size)
      const [first, last] = [parts[0], parts[parts.length - 1]]
      if (FILLER.has(first.small) || JOINS.has(first.small) || JOINS.has(last.small) || (FILLER.has(last.small) && size > 1)) continue
      if (parts.some(isNumber) || parts.some((part) => TIME.has(part.small))) continue
      const name = named(parts)
      const country = places.country(name.toLowerCase())
      if (country) return { spot: { kind: 'country', ...country }, from, to: from + size }
      const region = REGION_NAMED.get(name.toLowerCase())
      if (region) return { spot: { kind: 'region', code: region, name: REGIONS[region].name }, from, to: from + size }
      if (size === 1 && SUBJECTS.has(first.small)) continue
      const city = places.city(name)
      if (city) return { spot: { kind: 'city', ...city }, from, to: from + size }
    }
  }
  return null
}

/** What a request asks for: the period, the place, and what is left of it. */
export function understand(text: string, today: Day, places: Places): Understood {
  const period = read(text, today)
  const found = words(text)
  const where = place(found, places)
  const rest = found
    .filter((_, at) => !(where && at >= where.from && at < where.to))
    .filter((word) => !FILLER.has(word.small) && !TIME.has(word.small) && !isNumber(word))
    .map((word) => word.small)
  return { period, spot: where?.spot ?? null, rest }
}
