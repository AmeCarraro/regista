import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import * as icons from '../icons.tsx'
import { connect } from './bridge.ts'
import type { Answer, Heard, State } from './bridge.ts'
import type { Day } from './period.ts'
import { ofKind, partly, select, sentence } from './select.ts'
import type { Found } from './select.ts'
import { understand } from './understand.ts'

// how many pictures are shown at first, and how many more at each "Mostrane altre"
const PAGE = 120
const EXAMPLES = ['Le foto di questo mese', "Le foto dell'anno scorso", "Le foto dell'Italia"]

function today(): Day {
  const now = new Date()
  return { year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate() }
}

const count = (number: number) => (number === 1 ? '1 foto' : `${number} foto`)
const megabytes = (bytes: number) => Math.round(bytes / 1_000_000)

function linked(state: State): string {
  if (!state.paired) return 'Nessun computer collegato'
  return state.reachable ? `Collegato a ${state.computer || 'il computer'}` : 'Computer non raggiungibile'
}

/**
 * The phone's own screen: it looks for the pictures of this phone by when and where they were
 * taken and, once the phone has its own models, by what they show, with no computer and no
 * internet; and it puts the ones chosen in line for the computer.
 */
export default function Telefono() {
  const app = useMemo(() => connect(), [])
  const [pictures, setPictures] = useState(() => app.pictures())
  const [reading, setReading] = useState(() => app.reading())
  const [state, setState] = useState(() => app.state())
  const [sight, setSight] = useState(() => app.sight())
  const [copying, setCopying] = useState(() => app.autoCopy())
  const [update, setUpdate] = useState(() => app.update())
  // the pictures by kind, and the kind shown in place of all of them; nothing is moved
  const [kinds, setKinds] = useState(() => app.kinds())
  const [kind, setKind] = useState<string | null>(null)
  const [request, setRequest] = useState('')
  // the request the pictures on screen are the answer to
  const [asked, setAsked] = useState('')
  const [shown, setShown] = useState(PAGE)
  // the pictures ticked to go to the computer, while the user is choosing them
  const [choosing, setChoosing] = useState<Set<string> | null>(null)
  const [note, setNote] = useState('')
  // the computer's answer to the request on screen, when it gave one; and whether it is still being asked
  const [answered, setAnswered] = useState<{ asked: string; answer: Answer } | null>(null)
  const [waiting, setWaiting] = useState(false)
  // while the computer looks: the pictures it has found so far, and how many it has looked at, of how many
  const [soFar, setSoFar] = useState<{ asked: string; photos: string[]; looked: number; of: number } | null>(null)
  // the computer can be wrong too: the user may go back to the phone's own answer
  const [phoneFirst, setPhoneFirst] = useState(false)
  const latest = useRef('')
  const read = useRef(reading.done)

  // the app reads the pictures in its own time, and the computer comes and goes: both are asked again now and then
  useEffect(() => {
    const timer = setInterval(() => {
      const now = app.reading()
      if (now.done !== read.current) {
        read.current = now.done
        setPictures(app.pictures())
      }
      setReading(now)
      setState(app.state())
      setSight(app.sight())
      setCopying(app.autoCopy())
      setUpdate(app.update())
      // worked out again by the app only when the pictures or the kinds changed: else the same object, and nothing to redraw
      setKinds(app.kinds())
    }, 2000)
    return () => clearInterval(timer)
  }, [app])

  const understood = useMemo(() => understand(asked, today(), app.places), [asked, app])
  // what the pictures should show, asked of the phone's own model; again as it looks at more of them
  const scores = useMemo(
    () => (understood.rest.length > 0 && sight.ready ? app.scores(sentence(understood.rest)) : null),
    // sight.seen is not read here, and is what makes the answer change: the app has looked at more pictures
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [understood, sight.ready, sight.seen, app],
  )
  const shownKind = !asked && kind ? kinds?.kinds.find((one) => one.kind === kind) : undefined
  const mine = useMemo(
    () => (shownKind ? ofKind(pictures, shownKind) : select(pictures, understood, scores)),
    [pictures, understood, scores, shownKind],
  )
  // the computer's answer when there is one for this request, or while it looks what it has found so far: it names the phone's own pictures
  const computer: Found | null = useMemo(() => {
    if (answered?.asked === asked) {
      const byName = new Map(pictures.map((picture) => [picture.id, picture]))
      const sure = answered.answer.sure.flatMap((id) => byName.get(id) ?? [])
      const maybe = answered.answer.maybe.flatMap((id) => byName.get(id) ?? [])
      return { pictures: [...sure, ...maybe], words: answered.answer.words, sure: sure.length }
    }
    if (soFar?.asked !== asked) return null
    const partial = partly(pictures, soFar.photos)
    return partial.pictures.length > 0 ? partial : null
  }, [answered, soFar, asked, pictures])
  const both = computer !== null
  const found = computer && !phoneFirst ? computer : mine
  const fromComputer = found !== mine
  const visible = found.pictures.slice(0, shown)

  function ask(text: string) {
    const typed = text.trim()
    setRequest(text)
    setAsked(typed)
    setShown(PAGE)
    setChoosing(null)
    setNote('')
    setAnswered(null)
    setSoFar(null)
    setPhoneFirst(false)
    setKind(null)
    latest.current = typed
    // the phone answers at once, by itself; the computer, when it answers, understands more and has the last word
    if (!typed || !state.reachable) {
      setWaiting(false)
      return
    }
    setWaiting(true)
    // what the computer finds is shown as it finds it, in place of the phone's own answer
    const heard = (event: Heard) => {
      if (latest.current !== typed) return
      setSoFar((before) => {
        const now = before?.asked === typed ? before : { asked: typed, photos: [], looked: 0, of: 0 }
        return event.type === 'photo' ? { ...now, photos: [...now.photos, event.photo] } : { ...now, looked: event.looked, of: event.of }
      })
    }
    void app.ask(typed, heard).then((answer) => {
      if (latest.current !== typed) return
      setWaiting(false)
      setSoFar(null)
      if (answer) setAnswered({ asked: typed, answer })
    })
  }

  /** The pictures of a kind in place of all of them, or all of them again with null. */
  function chooseKind(chosen: string | null) {
    ask('')
    setKind(chosen)
  }

  function toggle(id: string) {
    setChoosing((before) => {
      const after = new Set(before)
      if (after.has(id)) after.delete(id)
      else after.add(id)
      return after
    })
  }

  function send() {
    if (!choosing) return
    const { queued } = app.send([...choosing])
    setNote(
      queued
        ? `Mando al computer ${count(queued)}, nella cartella «Dal telefono». ${state.reachable ? 'Comincio ora.' : 'Ora non lo raggiungo: lo faccio appena posso.'}`
        : 'Non sono riuscito a metterle in fila per il computer.',
    )
    setChoosing(null)
  }

  return (
    <main className="phone">
      <header className="top">
        <icons.Logo className="logo" />
        <div className="name">
          <b>Regista</b>
          <span>sul telefono</span>
        </div>
        <span className={state.reachable ? 'link on' : 'link'}>
          <i />
          {linked(state)}
        </span>
      </header>

      <form
        className="ask"
        onSubmit={(event) => {
          event.preventDefault()
          ask(request)
          // the keyboard goes away, so that the pictures found can be seen
          if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
        }}
      >
        <icons.Search />
        <input
          value={request}
          onChange={(event) => setRequest(event.target.value)}
          placeholder="Cerca tra le foto di questo telefono"
          aria-label="La tua richiesta"
          enterKeyHint="search"
          autoComplete="off"
        />
        <button type="submit" className="go" aria-label="Cerca">
          <icons.Arrow />
        </button>
      </form>

      {!asked && (
        <div className="examples">
          {EXAMPLES.map((example) => (
            <button type="button" key={example} onClick={() => ask(example)}>
              {example}
            </button>
          ))}
        </div>
      )}

      {!asked && kinds && kinds.kinds.some((one) => one.sure.length + one.maybe.length > 0) && (
        <div className="by-kind" role="tablist" aria-label="Le foto per tipo">
          <button type="button" role="tab" aria-selected={kind === null} onClick={() => chooseKind(null)}>
            Tutte
          </button>
          {kinds.kinds
            .filter((one) => one.sure.length + one.maybe.length > 0)
            .map((one) => (
              <button type="button" role="tab" key={one.kind} aria-selected={kind === one.kind} onClick={() => chooseKind(one.kind)}>
                {one.label} <small>{one.sure.length + one.maybe.length}</small>
              </button>
            ))}
        </div>
      )}
      {!asked && kind && kinds && kinds.unsorted > 0 && (
        <p className="fine">Altre {count(kinds.unsorted)} non sono ancora divise per tipo: lo faccio quando il telefono o il computer le hanno guardate.</p>
      )}

      {!asked && !kind && update.newer && (
        <section className="card">
          <b>C'è una versione nuova dell'app</b>
          {update.taking ? (
            <p>
              La prendo dal computer: {megabytes(update.got)} di {megabytes(update.size)} MB. Poi Android ti chiede se installarla.
            </p>
          ) : (
            <>
              <p>
                Ce l'ha il tuo computer: la installo da qui, senza cavo. Android ti chiede di confermare; poi l'app si chiude, e la riapri. La prima
                volta Android chiede anche il permesso di installare app da Regista: dallo, torna indietro e premi di nuovo «Aggiorna l'app».
              </p>
              <button type="button" className="go wide" onClick={() => {
                app.takeUpdate()
                setUpdate(app.update())
              }}>
                Aggiorna l'app
              </button>
            </>
          )}
        </section>
      )}

      {!asked && !kind && state.paired && (
        <section className="card">
          <b>Copia automatica sul computer</b>
          <p>
            {copying.on
              ? `Attiva: quando il telefono è sulla Wi-Fi di casa, le foto nuove vanno sul computer da sole, nella cartella «Dal telefono».${copying.count ? ` L'ultima volta ${count(copying.count)}, ${new Date(copying.at).toLocaleString('it-IT', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}.` : ''}`
              : "Quando il telefono è sulla Wi-Fi di casa, le foto nuove vanno sul computer da sole, anche con l'app chiusa. Quelle che ci sono già restano solo qui."}
          </p>
          <button
            type="button"
            className={copying.on ? 'quiet' : 'go wide'}
            onClick={() => {
              app.setAutoCopy(!copying.on)
              setCopying(app.autoCopy())
            }}
          >
            {copying.on ? 'Spegni' : 'Attiva'}
          </button>
        </section>
      )}

      {!reading.allowed && <p className="notice">Per cercare tra le foto mi serve il permesso di vederle: chiudi e riapri l'app, e dimmi di sì.</p>}
      {reading.allowed && reading.done < reading.total && (
        <p className="fine">
          Sto leggendo date e luoghi delle foto: {reading.done} di {reading.total}. Intanto cerco tra quelle già lette.
        </p>
      )}
      {sight.ready && sight.unseen > 0 && (
        <p className="fine">
          Sto guardando cosa mostrano le foto: {sight.seen} di {sight.seen + sight.unseen}. Intanto cerco tra quelle già viste.
        </p>
      )}
      {!sight.ready && (
        <section className="card">
          <b>Cercare cosa mostrano le foto, anche senza computer</b>
          {sight.wanted && sight.size > 0 ? (
            <p>
              Prendo il modello dal computer: {megabytes(sight.got)} di {megabytes(sight.size)} MB.
            </p>
          ) : sight.wanted ? (
            <p>{state.paired ? 'Prendo il modello dal computer appena lo raggiungo.' : 'Il modello arriva dal computer: collegalo dalla scheda «Computer».'}</p>
          ) : (
            <>
              <p>Per trovare «un cane» o «il mare» qui sul telefono serve un modello di circa 220 MB. Lo prendo una volta dal tuo computer, poi funziona da solo.</p>
              <button type="button" className="go wide" onClick={() => {
                app.wantSight()
                setSight(app.sight())
              }}>
                Prendi il modello
              </button>
            </>
          )}
        </section>
      )}

      <p className="words" role="status">
        {asked && state.paired && (
          <>
            <span className={fromComputer ? 'source computer' : 'source'}>{fromComputer ? 'dal computer' : 'dal telefono'}</span>{' '}
          </>
        )}
        {found.words}
      </p>
      {both && (
        <button type="button" className="switch" onClick={() => setPhoneFirst(!phoneFirst)}>
          {phoneFirst ? 'Mostra la risposta del computer' : 'Mostra la risposta del telefono'}
        </button>
      )}
      {waiting && (
        <p className="fine">
          {soFar?.asked === asked && soFar.of > 0
            ? `Il computer guarda le foto una per una: ${soFar.looked} di ${soFar.of}…`
            : 'Chiedo anche al computer, che capisce di più…'}
        </p>
      )}
      {note && (
        <p className="note">
          <icons.Check /> {note}
        </p>
      )}

      <ul className="grid">
        {visible.map((picture, index) => (
          <Fragment key={picture.id}>
            {index === found.sure && index > 0 && <li className="divider">Forse anche queste</li>}
            <li>
            <button
              type="button"
              className={choosing && !choosing.has(picture.id) ? 'tile off' : 'tile'}
              aria-label={picture.name}
              aria-pressed={choosing ? choosing.has(picture.id) : undefined}
              onClick={() => (choosing ? toggle(picture.id) : app.open(picture.id))}
            >
              <img src={app.thumb(picture.id)} alt="" loading="lazy" />
              {choosing && (
                <span className="tick">
                  <icons.Check />
                </span>
              )}
            </button>
            </li>
          </Fragment>
        ))}
      </ul>
      {found.pictures.length > shown && (
        <button type="button" className="more" onClick={() => setShown(shown + PAGE)}>
          Mostrane altre ({found.pictures.length - shown})
        </button>
      )}

      {visible.length > 0 && (
        <footer className="actions">
          {!state.paired ? (
            <p className="fine">Per mandare le foto al computer, collegalo dalla scheda «Computer».</p>
          ) : choosing ? (
            <>
              <button type="button" className="go wide" disabled={choosing.size === 0} onClick={send}>
                Manda {count(choosing.size)} al computer
              </button>
              <button type="button" className="quiet" onClick={() => setChoosing(null)}>
                Lascia stare
              </button>
            </>
          ) : (
            <button type="button" className="go wide" onClick={() => setChoosing(new Set(visible.map((picture) => picture.id)))}>
              <icons.Send /> Manda al computer
            </button>
          )}
        </footer>
      )}
      {choosing && <p className="fine center">Tocca una foto per lasciarla fuori.</p>}
    </main>
  )
}
