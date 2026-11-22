import { useEffect, useState } from 'react'
import { catalogRequest, type CatalogRequest } from './catalogApi.ts'
import './modelControl.css'

type Runtime = { model: string; loaded: boolean; installed: boolean; phase: string; busy: boolean; command: string;
  started: number; elapsed: number; checked: number; last_seconds: { load?: number; unload?: number }; problem: string; analysis_paused: boolean }
const seconds = (value: number) => value < 60 ? `${Math.floor(value)} s` : `${Math.floor(value / 60)} min ${Math.floor(value % 60)} s`

export default function ModelControl({ request = catalogRequest, visible = true }: { request?: CatalogRequest; visible?: boolean }) {
  const [state, setState] = useState<Runtime | null>(null)
  const [problem, setProblem] = useState('')
  const [sending, setSending] = useState(false)
  const [now, setNow] = useState(Date.now)
  const [measured, setMeasured] = useState(() => ({ at: Date.now(), elapsed: 0 }))
  function receive(value: Runtime) {
    setMeasured({ at: Date.now(), elapsed: value.elapsed })
    setState(before => before?.busy && !value.busy && value.checked < before.started ? before : value)
  }
  useEffect(() => {
    if (!visible) return
    let active = true, pending = false
    const read = async () => {
      if (pending) return
      pending = true
      try { const value = await request<Runtime>('/api/model-runtime'); if (active) { receive(value); setProblem('') } }
      catch (error) { if (active) setProblem(error instanceof Error ? error.message : String(error)) }
      finally { pending = false }
    }
    void read()
    const timer = setInterval(() => { setNow(Date.now()); void read() }, 1000)
    return () => { active = false; clearInterval(timer) }
  }, [request, visible])
  if (!visible) return null
  const busy = sending || state?.busy
  const elapsed = state?.busy ? measured.elapsed + Math.max(0, now - measured.at) / 1000 : 0
  async function change(command: 'load' | 'unload') {
    setSending(true); setProblem('')
    try { receive(await request<Runtime>('/api/model-runtime', { command })) }
    catch (error) { setProblem(error instanceof Error ? error.message : String(error)) }
    finally { setSending(false) }
  }
  return <section className="model-control" aria-label="Modello sul PC">
    <p className="model-control-name">{state?.model || 'Modello sul PC'}</p>
    <p role="status" className="model-control-status"><i className={state?.loaded ? 'on' : ''} />
      {state?.busy ? `${state.phase === 'waiting' ? 'Attendo la fine delle richieste' : state.command === 'load' ? 'Caricamento' : 'Scaricamento'} · ${seconds(elapsed)}`
        : state?.loaded ? 'In memoria sul PC' : 'Fuori memoria'}
    </p>
    <button type="button" disabled={!state || !!busy || (!state.installed && !state.loaded) || !!problem} onClick={() => void change(state?.loaded ? 'unload' : 'load')}>
      {busy ? 'Operazione in corso…' : state?.loaded ? 'Scarica dalla memoria' : 'Carica in memoria'}
    </button>
    {state && <p className="model-control-note">{state.busy && state.last_seconds[state.command as 'load' | 'unload'] !== undefined
      ? `Ultima durata: ${seconds(state.last_seconds[state.command as 'load' | 'unload']!)}. Il tempo attuale può variare.`
      : `Ultimo caricamento: ${state.last_seconds.load === undefined ? 'da misurare' : seconds(state.last_seconds.load)} · scaricamento: ${state.last_seconds.unload === undefined ? 'da misurare' : seconds(state.last_seconds.unload)}`}</p>}
    {state?.command === 'unload' && state.analysis_paused && <p className="model-control-note">Analisi AI in pausa. Una nuova richiesta a Qwen può ricaricare il modello.</p>}
    {(problem || state?.problem) && <p className="model-control-note" role="alert">{problem || state?.problem}</p>}
  </section>
}
