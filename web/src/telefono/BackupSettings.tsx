import { useEffect, useState } from 'react'
import './bridge.ts'

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
  return <section className="backup-settings" aria-label="Impostazioni backup completo">
    <h2>Backup completo sul PC</h2>
    <p>Cerca foto, immagini, musica, registrazioni audio e video nelle raccolte accessibili di Android, senza limitarsi a DCIM o alla musica. Include le cartelle supplementari che scegli qui sotto e le loro sottocartelle.</p>
    <p>Sul PC viene conservato uno ZIP verificato per ogni contenuto diverso. I doppioni già verificati non vengono ritrasmessi. Gli originali sul telefono restano intatti e questo backup non avvia l’AI.</p>
    <p>Android può nascondere cartelle private, contenuti cloud e file non concessi all’app. Il backup copre i contenuti accessibili: non può aggirare questi limiti.</p>
    {!state ? <p>Aggiorna l’app per utilizzare il backup completo.</p> : <>
      <p>{state.reachable ? `PC collegato · ${state.address}` : 'Collega il PC prima di avviare il backup.'}</p>
      {!!state.missing_permissions.length && <p>Servono i permessi per foto, video e audio. Il pulsante li richiede; poi torna qui e premi nuovamente per avviare.</p>}
      <button disabled={state.busy || !state.reachable} onClick={() => { window.Regista?.startMediaBackup?.(); setState(current()) }}>
        {state.busy ? 'Backup in corso…' : 'Sincronizza tutti i contenuti sul PC…'}
      </button>
      {state.busy && <button onClick={() => window.Regista?.cancelMediaBackup?.()}>Interrompi backup</button>}
      <p>Prima di iniziare viene mostrata una conferma. Lascia l’app aperta: durante il backup lo schermo resta acceso. Se si interrompe, avvialo di nuovo: i contenuti già verificati vengono saltati.</p>
      <p role="status">{phases[state.phase] || state.phase}{state.busy && state.current ? ` · ${state.current}` : ''}</p>
      {state.phase === 'uploading' && <p>{(state.bytes / 1024 ** 2).toFixed(1)} MB inviati su {(state.current_size / 1024 ** 2).toFixed(1)} MB del file attuale</p>}
      {(state.busy || state.phase !== 'idle') && <>
        <progress max={Math.max(1, state.total)} value={Math.min(state.total, state.copied + state.duplicates + state.failed)} aria-label="Avanzamento backup" />
        <p>{state.total} file trovati · {state.scanned} controllati · {state.copied} copiati · {state.duplicates} già presenti · {state.failed} errori</p>
        {state.complete && <p>Backup completato per i contenuti accessibili trovati durante questa scansione.</p>}
      </>}
      {state.error && <p role="alert">{state.error}</p>}
      {state.warnings?.map((warning, index) => <p key={`warning-${index}`}>{warning}</p>)}
      {!!state.errors?.length && <details><summary>Problemi da verificare</summary><ul>{state.errors.map((error, index) => <li key={index}>{error}</li>)}</ul></details>}
      <h3>Cartelle supplementari</h3>
      <p>Per file non indicizzati, ad esempio in cartelle con .nomedia, scegli le cartelle che Android ti permette di aprire. Saranno scandite al prossimo backup.</p>
      <button disabled={state.busy} onClick={() => window.Regista?.chooseBackupFolder?.()}>Aggiungi una cartella…</button>
      <ul>{state.folders.map(folder => <li key={folder.id}>{folder.name} <button disabled={state.busy} onClick={() => {
        window.Regista?.removeBackupFolder?.(folder.id); setState(current())
      }}>Togli dall’elenco</button></li>)}</ul>
      <h3>Trasferimento con il cavo</h3>
      <p>Collega il cavo USB, attiva il tethering USB nelle impostazioni del telefono e collega Regista al PC su quella rete. Il solo cavo in modalità ricarica o trasferimento file non basta.</p>
      <p>Per verificare che il trasferimento passi sul cavo, puoi disattivare il Wi-Fi del telefono prima di ricollegarlo. Il PC deve avere Regista aperto; la velocità dipende anche da porta USB, memoria e verifica degli ZIP.</p>
      <button onClick={() => window.Regista?.openBackupNetworkSettings?.()}>Apri impostazioni di rete</button>
      <button onClick={() => window.Regista?.openSettings?.()}>Permessi dell’app</button>
    </>}
  </section>
}
