import { useEffect, useRef, useState } from 'react'
import { answerPhone, forgetPhone, invitePhone } from './api.ts'
import type { Device, Invite, PhoneState } from './api.ts'
import * as icons from './icons.tsx'

const OPEN_DOOR = '.\\run.ps1 -Phone'
// a new code every half minute, for five minutes at most: a picture taken of the screen is soon of no use
const RENEW = 30_000
const SHOWN_FOR = 5 * 60_000

function clock(when: string): string {
  const date = new Date(when)
  if (Number.isNaN(date.getTime())) return ''
  const today = date.toDateString() === new Date().toDateString()
  const time = date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  return today ? `oggi alle ${time}` : `il ${date.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })} alle ${time}`
}

function DeviceRow({ device, onGone }: { device: Device; onGone: () => void }) {
  const [asking, setAsking] = useState(false)
  const seen = clock(device.seen)

  return (
    <li className="model">
      <p className="model-name">
        <icons.Phone />
        <b>{device.name}</b>
      </p>
      <p className="fine">
        {device.photos > 0
          ? `${device.photos.toLocaleString('it-IT')} foto conosciute`
          : 'Non ha ancora mandato le sue foto: apri Regista sul telefono.'}
        {seen && ` · sentito ${seen}`}
      </p>
      {device.waiting > 0 && (
        <p className="fine warn">
          Gli ho chiesto {device.waiting} foto: arrivano quando Regista è aperto sul telefono.
        </p>
      )}
      {asking ? (
        <p className="fine">
          Lo scollego? Non potrà più entrare, e dimentico le sue foto.{' '}
          <button type="button" className="link" onClick={() => void forgetPhone(device.id).then(onGone, onGone)}>
            Sì, scollega
          </button>{' '}
          <button type="button" className="link" onClick={() => setAsking(false)}>
            No
          </button>
        </p>
      ) : (
        <button type="button" className="link" onClick={() => setAsking(true)}>
          Scollega
        </button>
      )}
    </li>
  )
}

/**
 * The phones that may talk to this computer, and the way to let one in: a code to point the
 * phone at, which renews itself every half minute. The phone that reads it asks to come in, and
 * comes in only with a yes given here, to the request that shows the number the phone shows.
 */
export default function PhoneCard({ phone, onChange }: { phone: PhoneState | null; onChange: () => void }) {
  // the code on show, with how many phones were in when the codes began, and since when
  const [made, setMade] = useState<{ invite: Invite; paired: number; since: number } | null>(null)
  const [problem, setProblem] = useState('')
  const [copied, setCopied] = useState(false)
  const paired = phone?.devices.length ?? 0
  const pending = phone?.pending ?? []
  // the code has done its job when a phone asks to come in, or comes in
  const invite = made && made.paired === paired && pending.length === 0 ? made.invite : null
  const refresh = useRef(onChange)
  refresh.current = onChange

  // a new one every half minute, for a few minutes
  useEffect(() => {
    if (!invite || !made) return
    const timer = setTimeout(() => (Date.now() - made.since < SHOWN_FOR ? ask(made) : setMade(null)), RENEW)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invite, made])

  // while a phone may be asking, what the computer knows of the phones is asked again often
  useEffect(() => {
    if (!invite && pending.length === 0) return
    const timer = setInterval(() => refresh.current(), 2000)
    return () => clearInterval(timer)
  }, [invite, pending.length])

  function ask(before: { paired: number; since: number } | null = null) {
    setProblem('')
    setCopied(false)
    invitePhone().then(
      (fresh) => setMade({ invite: fresh, paired: before?.paired ?? paired, since: before?.since ?? Date.now() }),
      (error: unknown) => setProblem(error instanceof Error ? error.message : String(error)),
    )
  }

  function answer(request: string, yes: boolean) {
    // either way the codes on show are of no more use: the computer stopped taking them
    setMade(null)
    answerPhone(request, yes).then(onChange, (error: unknown) => {
      setProblem(error instanceof Error ? error.message : String(error))
      onChange()
    })
  }

  function copy(text: string) {
    void navigator.clipboard?.writeText(text).then(
      () => setCopied(true),
      () => setCopied(false),
    )
  }

  return (
    <section className="panel">
      <h2>
        <icons.Phone /> Telefono
      </h2>
      {!phone ? (
        <p className="fine">Non raggiungo il servizio.</p>
      ) : !phone.open ? (
        <>
          <p className="fine">La porta per i telefoni è chiusa: da fuori nessuno può entrare. Per aprirla alla rete di casa, riavvia Regista così:</p>
          <button type="button" className="command mono" onClick={() => copy(OPEN_DOOR)} title="Copia il comando">
            {OPEN_DOOR}
            <span>{copied ? 'copiato' : 'copia'}</span>
          </button>
        </>
      ) : (
        <>
          {paired > 0 && (
            <ul className="models">
              {phone.devices.map((device) => (
                <DeviceRow key={device.id} device={device} onGone={onChange} />
              ))}
            </ul>
          )}
          {pending.map((one) => (
            <div className="pending" key={one.id} role="alert">
              <p>
                <b>{one.name}</b> chiede di collegarsi. Sul telefono deve esserci questo numero:
              </p>
              <p className="pending-code mono">
                {one.code.slice(0, 3)} {one.code.slice(3)}
              </p>
              <div className="pending-answers">
                <button type="button" className="go" onClick={() => answer(one.id, true)}>
                  Collega
                </button>
                <button type="button" className="quiet-button" onClick={() => answer(one.id, false)}>
                  Rifiuta
                </button>
              </div>
              <p className="fine">Se il numero è diverso, o se non stai collegando un telefono adesso, rifiuta.</p>
            </div>
          ))}
          {invite ? (
            <div className="invite">
              <img src={invite.qr} alt="Codice per collegare il telefono" />
              <p className="fine">
                Apri la fotocamera del telefono e inquadra il codice: si apre Regista. Poi qui ti chiedo di confermare, con un numero da
                controllare sul telefono. Il codice cambia ogni 30 secondi: chi lo fotografa non può usarlo.
              </p>
              <button type="button" className="command mono" onClick={() => copy(invite.link)} title="Copia il collegamento">
                <i>{invite.link}</i>
                <span>{copied ? 'copiato' : 'copia'}</span>
              </button>
              <p className="fine">Se la fotocamera non lo legge, copia il collegamento e incollalo nell'app.</p>
            </div>
          ) : (
            pending.length === 0 && (
              <button type="button" className="quiet-button" onClick={() => ask()}>
                <icons.Phone /> {paired > 0 ? 'Collega un altro telefono' : 'Collega un telefono'}
              </button>
            )
          )}
          {problem && <p className="fine warn">Non ci sono riuscito: {problem}</p>}
          {phone.refused.count > 0 && (
            <p className="fine warn">
              Tentativi rifiutati alla porta dei telefoni: {phone.refused.count.toLocaleString('it-IT')}, l'ultimo {clock(phone.refused.last)}:{' '}
              {phone.refused.what}.
            </p>
          )}
          <p className="fine">
            Un telefono collegato manda qui una copia piccola delle sue foto, così le posso cercare. Gli originali restano sul telefono finché non
            me li chiedi. Tutto viaggia cifrato, e solo tra il telefono e questo computer.
          </p>
        </>
      )}
    </section>
  )
}
