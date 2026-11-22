import { useEffect, useState } from 'react'
import Catalog from '../Catalog.tsx'
import type { CatalogRequest } from '../catalogApi.ts'
import { connect } from './bridge.ts'
import OfflineCatalog from './OfflineCatalog.tsx'
import BackupSettings from './BackupSettings.tsx'
import PhoneHeader from './PhoneHeader.tsx'
import { Arrow, Back, Menu, Refresh } from '../icons.tsx'

let serial = 0
const request: CatalogRequest = <T,>(path: string, body?: unknown): Promise<T> => new Promise((resolve, reject) => {
  const native = window.Regista
  if (!native?.catalogRequest || !native.catalogResponse) { reject(new Error('Aggiorna l’app Regista sul telefono.')); return }
  const token = `${Date.now().toString(36)}${(++serial).toString(36)}`
  const deadline = Date.now() + 180_000
  native.catalogRequest(path, body === undefined ? '' : JSON.stringify(body), token)
  const poll = () => {
    const raw = native.catalogResponse!(token)
    if (raw) {
      try { const value = JSON.parse(raw); if (value.error) reject(new Error(value.error)); else resolve(value as T) }
      catch { reject(new Error('Risposta del PC non leggibile.')) }
    } else if (Date.now() > deadline) {
      native.cancelCatalog?.(token); reject(new Error('Il PC non risponde. Riprova quando è disponibile.'))
    } else setTimeout(poll, 300)
  }
  poll()
})
const mediaUrl = async (id: string, full: boolean) => `/catalog-media/${id}/${full ? 'full' : 'thumb'}`

export default function Telefono({ visible = true }: { visible?: boolean }) {
  const [state, setState] = useState(() => connect().state())
  const [copying, setCopying] = useState(() => connect().autoCopy())
  const [note, setNote] = useState('')
  const [update, setUpdate] = useState(() => connect().update())
  const [remote, setRemote] = useState(false)
  const [settings, setSettings] = useState(false)
  useEffect(() => {
    if (!visible) return
    const timer = setInterval(() => { setState(connect().state()); setCopying(connect().autoCopy()); setUpdate(connect().update()) }, 2000)
    return () => clearInterval(timer)
  }, [visible])
  return <main className="phone phone-catalog">
    <PhoneHeader section="foto">
      <button className="phone-icon phone-settings" aria-label={settings ? 'Torna alle foto' : 'Impostazioni e backup'}
        aria-expanded={settings} aria-controls="phone-settings" onClick={() => setSettings(value => !value)}>
        {settings ? <Back /> : <Menu />}
      </button>
    </PhoneHeader>
    <div className={`phone-connection${state.reachable ? ' on' : ''}`}><i />
      {state.reachable ? `Collegato a ${state.computer || 'PC'}` : 'PC non collegato'}
    </div>
    <div className="phone-intro"><h1>{settings ? 'Impostazioni' : 'Le tue foto'}</h1>
      <p>{settings ? 'Scegli cosa portare sul computer.' : 'Ritrova un ricordo, con poche parole.'}</p>
    </div>
    {update.newer && <button className="phone-action" onClick={() => connect().takeUpdate()}><Refresh />Aggiorna Regista</button>}
    {settings && visible && <div id="phone-settings" className="phone-settings-content">
      <section className="phone-panel" aria-label="Copia delle foto">
        <h2>Le foto sul computer</h2>
        <p>Copia le foto da catalogare. Le immagini identiche vengono trasferite una sola volta; i tag si creano dal PC.</p>
        <button className="phone-action" disabled={!state.reachable} onClick={() => {
        const answer = window.Regista?.importAll?.()
        if (!answer) { setNote('Aggiorna Regista sul telefono.'); return }
        const result = JSON.parse(answer)
        setNote(result.error || `${result.queued} foto in coda per il PC. Lascia aperta l’app durante l’importazione.`)
        }}>Importa tutte le foto sul PC<Arrow /></button>
        {!state.reachable && <p className="phone-caption">Collega il computer dalla scheda Computer per importare.</p>}
        <label className="phone-toggle"><span><b>Copia automatica</b><small>Invia le nuove foto quando il PC è disponibile.</small></span><input type="checkbox" checked={copying.on} onChange={event => {
        connect().setAutoCopy(event.target.checked); setCopying(connect().autoCopy())
        }} /></label>
        {note && <p className="phone-feedback" role="status">{note}</p>}
        {state.waiting > 0 && <p className="phone-caption">{state.waiting} foto attendono la copia.</p>}
        {copying.count > 0 && <p className="phone-caption">Ultima copia: {copying.count} foto.</p>}
      </section>
      <BackupSettings />
    </div>}
    <div hidden={settings}>
    <OfflineCatalog visible={visible && !settings} />
    {state.reachable && <div className="remote-catalog"><button className="phone-action" aria-expanded={remote} onClick={() => setRemote(value => !value)}>{remote ? 'Chiudi catalogo del PC' : 'Filtri e ricerca sul PC'}<Arrow /></button>
      {remote && <Catalog visible={visible && !settings} request={request} mediaUrl={mediaUrl} />}</div>}
    </div>
  </main>
}
