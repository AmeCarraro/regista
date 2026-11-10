import { useState } from 'react'
import { applyDemoTags, fetchCommandDemo, interpretDemo } from './api.ts'
import type { DemoPhoto, DemoProposal } from './api.ts'
import * as icons from './icons.tsx'

export default function CommandDemo({ initialPhotos, visible }: { initialPhotos: DemoPhoto[]; visible: boolean }) {
  const [photos, setPhotos] = useState(initialPhotos)
  const [selected, setSelected] = useState<string[]>([])
  const [found, setFound] = useState<string[] | null>(null)
  const [text, setText] = useState('')
  const [message, setMessage] = useState('')
  const [proposal, setProposal] = useState<DemoProposal | null>(null)
  const [working, setWorking] = useState(false)
  const [problem, setProblem] = useState('')

  async function tryCommand(work: () => Promise<void>) {
    setWorking(true)
    setProblem('')
    try {
      await work()
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  function setList(list: DemoPhoto[]) {
    setPhotos(list)
    setSelected((ids) => ids.filter((id) => list.some((photo) => photo.id === id)))
    setFound(null)
  }

  function send() {
    const request = text.trim()
    if (!request || working) return
    setProposal(null)
    setMessage('')
    void tryCommand(async () => {
      const answer = await interpretDemo(request, selected)
      setMessage(answer.message)
      setProposal(answer.proposal)
      if (answer.found !== null) {
        const matches = answer.found
        setFound(matches)
        setSelected((ids) => ids.filter((id) => matches.includes(id)))
      }
    })
  }

  function refresh() {
    void tryCommand(async () => {
      const response = await fetchCommandDemo()
      if (!response.available) throw new Error('La prova dei comandi non è disponibile.')
      setList(response.photos)
      setProposal(null)
      setMessage('')
    })
  }

  function confirm() {
    if (!proposal || working) return
    void tryCommand(async () => {
      const result = await applyDemoTags(proposal)
      setList(result.photos)
      setProposal(null)
      setMessage(result.changed === 1 ? '1 foto di prova aggiornata.' : `${result.changed} foto di prova aggiornate.`)
    })
  }

  function toggle(id: string) {
    setSelected((ids) => ids.includes(id) ? ids.filter((one) => one !== id) : [...ids, id])
    if (proposal) setMessage('')
    setProposal(null)
  }

  const shown = found === null ? photos : photos.filter((photo) => found.includes(photo.id))
  return (
    <section className="kinds command-demo" hidden={!visible} aria-labelledby="demo-title" aria-busy={working}>
      <div className="kinds-top">
        <h2 id="demo-title">Prova comandi</h2>
        <button type="button" className="quiet-button" onClick={refresh} disabled={working}>
          <icons.Refresh /> Aggiorna elenco
        </button>
      </div>
      <p className="fine">Questa prova usa una galleria fittizia. Cerca per tag oppure seleziona alcune foto di prova e chiedi di aggiungere o togliere un tag.</p>
      <form className="demo-form" onSubmit={(event) => { event.preventDefault(); send() }}>
        <label className="folder-name">
          <icons.Talk />
          <span>Comando</span>
          <input value={text} onChange={(event) => setText(event.target.value)} placeholder="Mostrami le foto dei cani" maxLength={500} disabled={working} />
        </label>
        <button type="submit" className="go" disabled={working || !text.trim()}>Invia</button>
      </form>
      {working && <p role="status" className="fine">Un attimo…</p>}
      {message && <p role="status">{message}</p>}
      {problem && <p role="alert" className="fine warn">{problem}</p>}
      {proposal && (
        <div className="proposal">
          <p>{proposal.action === 'add_tag' ? 'Aggiungi' : 'Togli'} «{proposal.tag}»</p>
          <ul className="fine">
            {proposal.ids.map((id) => <li key={id}>{photos.find((photo) => photo.id === id)?.name ?? id}</li>)}
          </ul>
          <footer>
            <button type="button" className="go" disabled={working} onClick={confirm}>Conferma</button>
            <button type="button" className="quiet-button" disabled={working} onClick={() => { setProposal(null); setMessage('Proposta annullata.') }}>
              Annulla
            </button>
          </footer>
        </div>
      )}
      <div className="kinds-top">
        <p className="fine">{selected.length} selezionate</p>
        {found !== null && <button type="button" className="link" disabled={working} onClick={() => setFound(null)}>Mostra tutte</button>}
      </div>
      {shown.length > 0 ? (
        <ul className="folders">
          {shown.map((photo) => (
            <li key={photo.id}>
              <label className="folder demo-photo">
                <span><input type="checkbox" checked={selected.includes(photo.id)} onChange={() => toggle(photo.id)} disabled={working} /> {photo.name}</span>
                <small>{photo.tags.join(' · ') || 'Nessun tag'}</small>
              </label>
            </li>
          ))}
        </ul>
      ) : <p className="fine">Nessuna foto di prova da mostrare.</p>}
    </section>
  )
}
