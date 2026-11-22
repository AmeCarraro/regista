import { useEffect, useState } from 'react'
import Catalog from '../Catalog.tsx'
import type { CatalogRequest } from '../catalogApi.ts'
import { connect } from './bridge.ts'
import OfflineCatalog from './OfflineCatalog.tsx'
import BackupSettings from './BackupSettings.tsx'
import ImportStatus from './ImportStatus.tsx'
import ModelControl from '../ModelControl.tsx'
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
  const [note, setNote] = useState('')
  const [update, setUpdate] = useState(() => connect().update())
  const [remote, setRemote] = useState(false)
  const [settings, setSettings] = useState(false)
  useEffect(() => {
    if (!visible) return
    const timer = setInterval(() => { setState(connect().state()); setUpdate(connect().update()) }, 2000)
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
    {visible && <ImportStatus />}
    {state.reachable && <ModelControl request={request} visible={visible} />}
    {settings && visible && <div id="phone-settings" className="phone-settings-content">
      <section className="phone-panel" aria-label="Copia delle foto">
        <h2>Foto e video sul computer</h2>
        <p>Copia foto e video da catalogare. I contenuti identici passano una sola volta. Alla fine del blocco il PC crea uno ZIP verificato, oltre alle copie normali.</p>
        <button className="phone-action" disabled={!state.reachable} onClick={() => {
        const answer = window.Regista?.importAll?.()
        if (!answer) { setNote('Aggiorna Regista sul telefono.'); return }
        const result = JSON.parse(answer)
        setNote(result.error || result.message || 'Importazione richiesta. Puoi seguirla nella notifica e spegnere lo schermo.')
        }}>Importa foto e video sul PC<Arrow /></button>
        {!state.reachable && <p className="phone-caption">Collega il computer dalla scheda Computer per importare.</p>}
        {note && <p className="phone-feedback" role="status">{note}</p>}
        {state.waiting > 0 && <p className="phone-caption">{state.waiting} foto attendono la copia.</p>}
      </section>
      <BackupSettings />
      <section className="phone-panel"><h2>I documenti sul PC</h2><p>Importa PDF, Excel, Word, CSV e TXT dalle cartelle autorizzate o scegli i singoli file. Ogni tipo ha il proprio ZIP per blocco. WhatsApp e Telegram mantengono archivi, provenienza e tag separati.</p>
        <button className="phone-action" disabled={!state.reachable} onClick={() => window.Regista?.importDocuments?.()}>Importa e indicizza documenti<Arrow /></button>
        <p className="phone-caption">Poi cercali nella chat del Computer: “Mandami il PDF della bolletta di ottobre”. Anche i documenti senza testo restano archiviati e cercabili per nome.</p>
      </section>
      <details className="phone-panel"><summary>Collegarsi da un’altra rete</summary><p>Configura una VPN privata, per esempio Tailscale, sul PC e sul telefono. Collega Regista all’indirizzo privato del PC nella VPN. Il PC deve essere acceso con Regista aperto.</p><p className="phone-caption">La VPN va configurata sui due dispositivi. Il collegamento conserva l’abbinamento e la verifica del certificato del PC.</p></details>
    </div>}
    <div hidden={settings}>
    <OfflineCatalog visible={visible && !settings} />
    {state.reachable && <div className="remote-catalog"><button className="phone-action" aria-expanded={remote} onClick={() => setRemote(value => !value)}>{remote ? 'Chiudi catalogo del PC' : 'Filtri e ricerca sul PC'}<Arrow /></button>
      {remote && <Catalog visible={visible && !settings} request={request} mediaUrl={mediaUrl} />}</div>}
    </div>
  </main>
}
