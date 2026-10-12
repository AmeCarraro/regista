import { useEffect, useState } from 'react'
import { forgetPhone, invitePhone } from './api.ts'
import type { Device, Invite, PhoneState } from './api.ts'
import * as icons from './icons.tsx'

const OPEN_DOOR = '.\\run.ps1 -Phone'

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
 * The phones that may talk to this computer, and the way to let one in: a code to
 * point the phone at. The code is good for a few minutes and for one phone.
 */
export default function PhoneCard({ phone, onChange }: { phone: PhoneState | null; onChange: () => void }) {
  // the code on show, with how many phones were in when it was made
  const [made, setMade] = useState<{ invite: Invite; paired: number } | null>(null)
  const [problem, setProblem] = useState('')
  const [copied, setCopied] = useState(false)
  const paired = phone?.devices.length ?? 0
  // the code has done its job when a phone comes in
  const invite = made && made.paired === paired ? made.invite : null

  // and it is of no use once its time is up
  useEffect(() => {
    if (!made) return
    const timer = setTimeout(() => setMade(null), made.invite.seconds * 1000)
    return () => clearTimeout(timer)
  }, [made])

  function ask() {
    setProblem('')
    setCopied(false)
    invitePhone().then(
      (fresh) => setMade({ invite: fresh, paired }),
      (error: unknown) => setProblem(error instanceof Error ? error.message : String(error)),
    )
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
          {invite ? (
            <div className="invite">
              <img src={invite.qr} alt="Codice per collegare il telefono" />
              <p className="fine">
                Apri la fotocamera del telefono e inquadra il codice: si apre Regista e si collega. Vale {Math.round(invite.seconds / 60)} minuti,
                per un solo telefono.
              </p>
              <button type="button" className="command mono" onClick={() => copy(invite.link)} title="Copia il collegamento">
                <i>{invite.link}</i>
                <span>{copied ? 'copiato' : 'copia'}</span>
              </button>
              <p className="fine">Se la fotocamera non lo legge, copia il collegamento e incollalo nell'app.</p>
            </div>
          ) : (
            <button type="button" className="quiet-button" onClick={ask}>
              <icons.Phone /> {paired > 0 ? 'Collega un altro telefono' : 'Collega un telefono'}
            </button>
          )}
          {problem && <p className="fine warn">Non sono riuscito a preparare il codice: {problem}</p>}
          <p className="fine">
            Un telefono collegato manda qui una copia piccola delle sue foto, così le posso cercare. Gli originali restano sul telefono finché non
            me li chiedi. Tutto viaggia cifrato, e solo tra il telefono e questo computer.
          </p>
        </>
      )}
    </section>
  )
}
