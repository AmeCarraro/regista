import { useEffect, useState } from 'react'
import './bridge.ts'
import { Arrow, Folder, Plus, Refresh } from '../icons.tsx'

type BackupState = { busy: boolean; phase: string; total: number; scanned: number; copied: number;
  duplicates: number; failed: number; current: string; error: string; errors: string[]; warnings: string[];
  bytes: number; current_size: number;
  complete: boolean; paired: boolean; reachable: boolean; address: string; missing_permissions: string[];
  folders: { id: string; name: string }[] }
function current(): BackupState | null {
  try { return JSON.parse(window.Regista?.mediaBackupState?.() || 'null') as BackupState | null }
  catch { return null }
}
const phases: Record<string, string> = { idle: 'Pronto', scanning: 'Scansione delle cartelle', hashing: 'Controllo dei contenuti',
  uploading: 'Copia e verifica sul PC', done: 'Terminato', error: 'Da riprovare', cancelled: 'Interrotto', cancelling: 'Interruzione in corso' }

export default function BackupSettings() {
  const [state, setState] = useState(current)
  useEffect(() => {
    const timer = setInterval(() => setState(current()), 1000)
    return () => clearInterval(timer)
  }, [])
  return <section className="phone-panel backup-settings" aria-label="Impostazioni backup completo">
    <div className="phone-section-heading"><h2>Una copia al sicuro</h2><Folder /></div>
    <p>Foto, musica, audio e video in ZIP verificati sul PC. Si copiano solo i contenuti nuovi, lasciando gli originali sul telefono.</p>
    {!state ? <p>Aggiorna l’app per utilizzare il backup completo.</p> : <>
      {!state.reachable && <p className="phone-caption">Collega il PC prima di avviare il backup.</p>}
      {!!state.missing_permissions.length && <p className="phone-caption">Servono i permessi per foto, video e audio. Premi Sincronizza per concederli, poi torna qui per avviare.</p>}
      <button className="phone-action primary" disabled={state.busy || !state.reachable} onClick={() => { window.Regista?.startMediaBackup?.(); setState(current()) }}><Refresh />
        {state.busy ? 'Backup in corso…' : 'Sincronizza tutti i contenuti…'}
      </button>
      {state.busy && <button className="phone-action" onClick={() => window.Regista?.cancelMediaBackup?.()}>Interrompi backup</button>}
      <p className="phone-caption">Ti chiederò conferma prima di iniziare. Durante la copia lascia l’app aperta.</p>
      <p className="backup-phase" role="status">{phases[state.phase] || state.phase}{state.busy && state.current ? ` · ${state.current}` : ''}</p>
      {state.phase === 'uploading' && <p className="phone-caption">{(state.bytes / 1024 ** 2).toFixed(1)} MB su {(state.current_size / 1024 ** 2).toFixed(1)} MB del file attuale</p>}
      {(state.busy || state.phase !== 'idle') && <>
        <progress max={Math.max(1, state.total)} value={Math.min(state.total, state.copied + state.duplicates + state.failed)} aria-label="Avanzamento backup" />
        <div className="backup-counts"><span><b>{state.copied}</b>copiati</span><span><b>{state.duplicates}</b>già presenti</span><span><b>{state.scanned} / {state.total}</b>controllati</span><span><b>{state.failed}</b>errori</span></div>
        {state.complete && <p className="phone-caption">Backup completato per i contenuti accessibili trovati.</p>}
      </>}
      {state.error && <p className="phone-feedback" role="alert">{state.error}</p>}
      {state.warnings?.map((warning, index) => <p className="phone-feedback" key={`warning-${index}`}>{warning}</p>)}
      {!!state.errors?.length && <details><summary>Problemi da verificare</summary><ul>{state.errors.map((error, index) => <li key={index}>{error}</li>)}</ul></details>}
      <details className="backup-detail"><summary>Cartelle supplementari{state.folders.length ? ` · ${state.folders.length}` : ''}</summary>
      <p>Aggiungi le cartelle non presenti nelle raccolte di Android. Verranno incluse, con le sottocartelle, nel prossimo backup.</p>
      <button className="phone-action" disabled={state.busy} onClick={() => window.Regista?.chooseBackupFolder?.()}><Plus />Aggiungi una cartella</button>
      <ul className="backup-folders">{state.folders.map(folder => <li key={folder.id}><span>{folder.name}</span><button className="phone-action" disabled={state.busy} onClick={() => {
        window.Regista?.removeBackupFolder?.(folder.id); setState(current())
      }}>Togli</button></li>)}</ul></details>
      <details className="backup-detail"><summary>Trasferire con il cavo USB</summary>
        <p>Collega il cavo, attiva il tethering USB sul telefono e collega Regista al PC su quella rete. La sola modalità ricarica o trasferimento file non basta.</p>
        <p>Per essere sicuro di usare il cavo, disattiva il Wi-Fi prima di ricollegarti. Regista deve restare aperto sul PC.</p>
        <button className="phone-action" onClick={() => window.Regista?.openBackupNetworkSettings?.()}>Impostazioni di rete<Arrow /></button>
      </details>
      <details className="backup-detail"><summary>Cosa viene salvato</summary>
        <p>Tutte le raccolte accessibili di foto, audio e video e le cartelle supplementari scelte. Android può nascondere cartelle private, file cloud e contenuti senza permesso: questi non sono inclusi.</p>
        <p>Ogni contenuto diverso viene salvato in uno ZIP verificato. Il backup non avvia l’analisi AI. Se lo interrompi, al prossimo avvio vengono saltati i contenuti già verificati.</p>
        <button className="phone-action" onClick={() => window.Regista?.openSettings?.()}>Permessi dell’app<Arrow /></button>
      </details>
    </>}
  </section>
}
