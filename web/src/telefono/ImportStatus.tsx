import { useEffect, useState } from 'react'
import './bridge.ts'

type ImportState = { busy: boolean; phase: string; total: number; processed: number; copied: number; duplicates: number;
  failed: number; remaining: number; message: string; scope: string; transport: string; blocks?: number; blocks_ready?: number }
function importState(): ImportState | null {
  try { return JSON.parse(window.Regista?.photoImportState?.() || 'null') as ImportState | null } catch { return null }
}
const transportName = (transport: string) => ({ usb: 'Cavo USB', wifi: 'Wi-Fi', wired: 'Rete cablata', local: 'Rete privata / VPN' }[transport] || 'Rete da verificare')

export default function ImportStatus() {
  const [state, setState] = useState(importState)
  useEffect(() => { const timer = setInterval(() => setState(importState()), 1000); return () => clearInterval(timer) }, [])
  if (!state || state.phase === 'idle' || !state.phase) return null
  return <div className="phone-panel" aria-label="Avanzamento importazione">
    <h2>{state.phase === 'done' ? 'Archivio completato' : state.busy ? 'Importazione in corso' : 'Importazione in pausa'}</h2>
    <p role="status" className="phone-caption">{state.message}</p>
    <progress max={Math.max(1, state.total)} value={state.processed} aria-label="File verificati sul PC" />
    <p className="phone-caption">{state.processed} / {state.total} file · {state.copied} copiati · {state.duplicates} già presenti{state.failed > 0 && ` · ${state.failed} da riprovare`}</p>
    <p className="phone-caption">{transportName(state.transport)}{state.busy && ' · Puoi spegnere lo schermo o aprire un’altra app.'}</p>
    {!!state.blocks && <p className="phone-caption">{state.blocks_ready || 0} / {state.blocks} blocchi ZIP verificati</p>}
    {state.busy && <button className="phone-action" onClick={() => window.Regista?.cancelPhotoImport?.()}>Metti in pausa</button>}
    {!state.busy && state.phase !== 'done' && <button className="phone-action" onClick={() => window.Regista?.importAll?.()}>Riprendi importazione</button>}
    {!state.busy && state.phase === 'paused' && <details><summary>La selezione precedente non è più disponibile?</summary><p className="phone-caption">Un nuovo blocco controlla i file accessibili adesso. Le copie e i blocchi precedenti restano sul PC.</p><button className="phone-action" onClick={() => window.Regista?.newImportBlock?.()}>Avvia un nuovo blocco</button></details>}
  </div>
}
