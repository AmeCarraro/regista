// A period of time in a request written in Italian, read on the phone itself: the same ways of
// saying it that app/period.py reads on the computer, and the same answers, so that a request
// finds the same pictures wherever it is made. A way of saying a period that is not among
// these is simply not read as one.

/** A day of the calendar. */
export type Day = { year: number; month: number; day: number }

/** A period, from its first day to its last, both included. */
export type Period = [Day, Day]

export const MONTHS = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']
const MONTH = `(${MONTHS.join('|')})`
const DAY = '(\\d{1,2})[º°]?'
const YEAR = '((?:19|20)\\d{2})'
const FROM = "\\b(?:dal|dall['’]|da|tra il|tra l['’]|fra il|fra l['’])\\s*"
const TO = "\\s+(?:al|all['’]|a|e il|e l['’]|e)\\s*"

// from a day to a day, with the months by name: "dal 20 maggio al 20 luglio 2024", "dal 1 al 15 agosto"
const DAYS = new RegExp(`${FROM}${DAY}(?:\\s+${MONTH})?(?:\\s+${YEAR})?${TO}${DAY}\\s+${MONTH}(?:\\s+${YEAR})?`)
// the same in numbers: "dal 20/5 al 20/7/2024"
const NUMBERS = new RegExp(`${FROM}(\\d{1,2})[/.-](\\d{1,2})(?:[/.-](\\d{2,4}))?${TO}(\\d{1,2})[/.-](\\d{1,2})(?:[/.-](\\d{2,4}))?`)
// from a month to a month: "da maggio a luglio"
const MONTH_TO_MONTH = new RegExp(`\\b(?:da|tra|fra)\\s+${MONTH}(?:\\s+${YEAR})?\\s+(?:a|ad|e)\\s+${MONTH}(?:\\s+${YEAR})?`)
// from a year to a year: "dal 2019 al 2021"
const YEARS = new RegExp(`\\b(?:dal|tra il|fra il)\\s+${YEAR}\\s+(?:al|e il)\\s+${YEAR}\\b`)
const ONE_DAY = new RegExp(`\\b${DAY}\\s+${MONTH}(?:\\s+${YEAR})?`)
const ONE_DAY_NUMBERS = /\b(\d{1,2})[/.-](\d{1,2})[/.-]((?:19|20)\d{2})\b/
const ONE_MONTH = new RegExp(`\\b${MONTH}(?:\\s+(?:del\\s+)?${YEAR})?`)
const ONE_YEAR = new RegExp(`\\b(?:del|nel|dell['’]anno|anno)\\s+${YEAR}\\b`)
const LAST = /\bultim[ie]\s+(\d{1,3})\s+(giorni|settimane|mesi)\b/

/** A day that exists, or an error: the 31st of February is not a day anyone can mean. */
function made(year: number, month: number, day: number): Day {
  const date = new Date(Date.UTC(year, month - 1, day))
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) throw new RangeError('no such day')
  return { year, month, day }
}

function toDate(day: Day): Date {
  return new Date(Date.UTC(day.year, day.month - 1, day.day))
}

function fromDate(date: Date): Day {
  return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() }
}

export function plusDays(day: Day, days: number): Day {
  return fromDate(new Date(toDate(day).getTime() + days * 86_400_000))
}

/** A day as "2024-08-15": the way the pictures' days are written, and in which order is time order. */
export function iso(day: Day): string {
  return `${day.year}-${String(day.month).padStart(2, '0')}-${String(day.day).padStart(2, '0')}`
}

function after(one: Day, other: Day): boolean {
  return iso(one) > iso(other)
}

function monthEnd(year: number, month: number): Day {
  return { year, month, day: new Date(Date.UTC(year, month, 0)).getUTCDate() }
}

/** The same day some years earlier; the 29th of February becomes the 28th. */
function yearsBack(day: Day, years: number): Day {
  try {
    return made(day.year - years, day.month, day.day)
  } catch {
    return { year: day.year - years, month: day.month, day: 28 }
  }
}

function fullYear(text: string | undefined): number | null {
  if (!text) return null
  return text.length === 4 ? Number(text) : 2000 + Number(text)
}

/** A period from (day, month, year or null) to (day, month, year or null), with the years it does not say worked out. */
function between(first: [number, number, number | null], last: [number, number, number | null], today: Day): Period {
  const [day1, month1, year1] = first
  const [day2, month2, said2] = last
  const said = year1 !== null || said2 !== null
  const year2 = said2 ?? year1 ?? today.year
  const until = made(year2, month2, day2)
  let since = made(year1 ?? year2, month1, day1)
  if (after(since, until)) {
    // "dal 20 dicembre al 5 gennaio": the first day is in the year before
    since = yearsBack(since, 1)
  }
  if (!said && after(since, today)) {
    // no year was said and this one has not got there yet: pictures are of the past, so it is last year's
    return [yearsBack(since, 1), yearsBack(until, 1)]
  }
  return [since, until]
}

const month = (name: string) => MONTHS.indexOf(name) + 1

/** The period a request names, or null if it names none that is understood. */
export function read(written: string, today: Day): Period | null {
  const text = written.toLowerCase()
  try {
    let found = DAYS.exec(text)
    if (found) {
      const [, day1, month1, year1, day2, month2, year2] = found
      const last = month(month2)
      return between([Number(day1), month1 ? month(month1) : last, fullYear(year1)], [Number(day2), last, fullYear(year2)], today)
    }
    if ((found = NUMBERS.exec(text))) {
      const [, day1, month1, year1, day2, month2, year2] = found
      return between([Number(day1), Number(month1), fullYear(year1)], [Number(day2), Number(month2), fullYear(year2)], today)
    }
    if ((found = MONTH_TO_MONTH.exec(text))) {
      const [, month1, year1, month2, year2] = found
      // how long the last month is depends on its year, which is worked out first
      const [since, until] = between([1, month(month1), fullYear(year1)], [28, month(month2), fullYear(year2)], today)
      return [since, monthEnd(until.year, until.month)]
    }
    if ((found = YEARS.exec(text))) {
      const [first, last] = [Number(found[1]), Number(found[2])].sort((one, other) => one - other)
      return [made(first, 1, 1), made(last, 12, 31)]
    }

    const monday = plusDays(today, -((toDate(today).getUTCDay() + 6) % 7))
    if (/\bl['’]altro ?ieri\b/.test(text)) return [plusDays(today, -2), plusDays(today, -2)]
    if (/\bieri\b/.test(text)) return [plusDays(today, -1), plusDays(today, -1)]
    if (/\boggi\b/.test(text)) return [today, today]
    if (/\b(?:settimana scorsa|scorsa settimana)\b/.test(text)) return [plusDays(monday, -7), plusDays(monday, -1)]
    if (/\bquesta settimana\b/.test(text)) return [monday, today]
    if (/\b(?:mese scorso|scorso mese)\b/.test(text)) {
      const before = plusDays({ ...today, day: 1 }, -1)
      return [{ ...before, day: 1 }, before]
    }
    if (/\bquesto mese\b/.test(text)) return [{ ...today, day: 1 }, today]
    if (/\b(?:anno scorso|scorso anno)\b/.test(text)) return [made(today.year - 1, 1, 1), made(today.year - 1, 12, 31)]
    if (/\bquest['’] ?anno\b/.test(text)) return [made(today.year, 1, 1), today]
    if ((found = LAST.exec(text))) {
      const days = Number(found[1]) * { giorni: 1, settimane: 7, mesi: 30 }[found[2] as 'giorni' | 'settimane' | 'mesi']
      return [plusDays(today, -days), today]
    }

    if ((found = ONE_DAY.exec(text))) {
      const [, day, name, year] = found
      let one = made(fullYear(year) ?? today.year, month(name), Number(day))
      if (!year && after(one, today)) one = yearsBack(one, 1)
      return [one, one]
    }
    if ((found = ONE_DAY_NUMBERS.exec(text))) {
      const one = made(Number(found[3]), Number(found[2]), Number(found[1]))
      return [one, one]
    }
    if ((found = ONE_MONTH.exec(text))) {
      const number = month(found[1])
      // a month that has not come yet this year is last year's
      const year = fullYear(found[2]) ?? (after(made(today.year, number, 1), today) ? today.year - 1 : today.year)
      return [made(year, number, 1), monthEnd(year, number)]
    }
    if ((found = ONE_YEAR.exec(text))) {
      const year = Number(found[1])
      return [made(year, 1, 1), made(year, 12, 31)]
    }
  } catch {
    return null
  }
  return null
}

/** A period as it is said in Italian after "le foto": "di agosto 2024", "dal 20 maggio al 20 luglio 2026". */
export function inWords([since, until]: Period): string {
  const name = (day: Day) => MONTHS[day.month - 1]
  // "dell'1", "dell'8", "dell'11": the days whose name starts with a vowel
  const vowel = (day: Day) => [1, 8, 11].includes(day.day)
  if (iso(since) === iso(until)) return `${vowel(since) ? "dell'" : 'del '}${since.day} ${name(since)} ${since.year}`
  if (since.day === 1 && since.month === 1 && until.day === 31 && until.month === 12 && since.year === until.year) return `del ${since.year}`
  if (since.day === 1 && iso(until) === iso(monthEnd(since.year, since.month))) return `di ${name(since)} ${since.year}`
  const first = `${since.day} ${name(since)}` + (since.year === until.year ? '' : ` ${since.year}`)
  return `${vowel(since) ? "dall'" : 'dal '}${first} ${vowel(until) ? "all'" : 'al '}${until.day} ${name(until)} ${until.year}`
}
