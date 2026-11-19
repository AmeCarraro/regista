import { useEffect, useState } from 'react'
import Catalog from '../Catalog.tsx'
import type { CatalogRequest } from '../catalogApi.ts'
import { connect } from './bridge.ts'
import OfflineCatalog from './OfflineCatalog.tsx'
import BackupSettings from './BackupSettings.tsx'

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
  return <div className="phone-catalog">
    <div style={{ padding: '16px' }}>
      <h1>Le tue foto</h1>
      <button aria-expanded={settings} onClick={() => setSettings(value => !value)}>{settings ? 'Chiudi impostazioni' : 'Impostazioni e backup'}</button>
      <p>{state.reachable ? `Collegato a ${state.computer || 'PC'}` : 'PC non raggiungibile. Puoi cercare nella copia del catalogo già salvata sul telefono.'}</p>
      <p>Importa le immagini da tutte le cartelle accessibili ad Android. I contenuti identici vengono copiati una sola volta. I tag si avviano dal PC.</p>
      <button onClick={() => {
        const answer = window.Regista?.importAll?.()
        if (!answer) { setNote('Aggiorna Regista sul telefono.'); return }
        const result = JSON.parse(answer)
        setNote(result.error || `${result.queued} foto in coda per il PC. Lascia aperta l’app durante l’importazione.`)
      }}>Importa tutte le foto sul PC</button>
      <label style={{ display: 'block', marginTop: '12px' }}><input type="checkbox" checked={copying.on} onChange={event => {
        connect().setAutoCopy(event.target.checked); setCopying(connect().autoCopy())
      }} /> Copia automaticamente le nuove foto</label>
      {note && <p role="status">{note}</p>}
      {state.waiting > 0 && <p>{state.waiting} foto attendono la copia.</p>}
      {copying.count > 0 && <p>Ultima copia: {copying.count} foto.</p>}
      {update.newer && <button onClick={() => connect().takeUpdate()}>Aggiorna Regista</button>}
    </div>
    {settings && visible && <BackupSettings />}
    <OfflineCatalog visible={visible} />
    {state.reachable && <div className="remote-catalog"><button onClick={() => setRemote(value => !value)}>{remote ? 'Chiudi catalogo del PC' : 'Apri filtri e ricerca del PC'}</button>
      {remote && <Catalog visible={visible} request={request} mediaUrl={mediaUrl} />}</div>}
  </div>
}
