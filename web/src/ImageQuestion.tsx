import { useState } from 'react'
import type { FormEvent } from 'react'

export default function ImageQuestion() {
  const [file, setFile] = useState<File | null>(null)
  const [question, setQuestion] = useState('Che cosa mostra questa immagine?')
  const [answer, setAnswer] = useState('')
  const [token, setToken] = useState('')
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setBusy(true); setProblem(''); setAnswer(''); setToken(''); setSaved(false)
    try {
      if (file.size > 16 * 1024 * 1024) throw new Error('Massimo 16 MB per immagine.')
      const response = await fetch(`/api/catalog/question?question=${encodeURIComponent(question)}`, { method: 'POST', body: file })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail)
      setAnswer(result.answer); setToken(result.attachment)
    } catch (error) { setProblem(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }
  async function save() {
    setBusy(true); setProblem('')
    try {
      const response = await fetch(`/api/catalog/attachments/${token}/save`, { method: 'POST' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail)
      setSaved(true)
    } catch (error) { setProblem(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }
  return <details className="image-question" style={{ margin: '16px', padding: '16px', border: '1px solid var(--line)', borderRadius: '14px' }}>
    <summary>Fai una domanda su un’immagine</summary>
    <form onSubmit={event => void ask(event)}>
      <label>Immagine (temporanea, massimo 16 MB)<input type="file" accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff" onChange={event => {
        setFile(event.target.files?.[0] || null); setToken(''); setAnswer(''); setSaved(false)
      }} /></label>
      <label>Domanda<input value={question} onChange={event => setQuestion(event.target.value)} maxLength={1000} required /></label>
      <button disabled={busy || !file}>{busy ? 'Attendi…' : 'Chiedi a Qwen'}</button>
    </form>
    {problem && <p role="alert">{problem}</p>}
    {answer && <p>{answer}</p>}
    {token && !saved && <button disabled={busy} onClick={() => void save()}>Salva nel catalogo</button>}
    {saved && <p role="status">Immagine salvata. I tag restano in pausa finché premi Avvia nel Catalogo.</p>}
  </details>
}
