import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { Models } from './api.ts'
import { placement, purposes, talkers } from './chat.ts'
import * as icons from './icons.tsx'

type Props = {
  models: Models | null
  /** "auto", or the name of the model chosen to do the talking. */
  model: string
  onModel: (name: string) => void
  busy: boolean
  onSend: (text: string) => void
  onStop: () => void
}

/** Where a request is written, and where the user says who should answer it. */
export default function Composer({ models, model, onModel, busy, onSend, onStop }: Props) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const picker = useRef<HTMLDivElement>(null)
  const choices = models ? talkers(models) : []
  const automatic = choices[0]?.name

  // the list of models closes when the user clicks elsewhere or presses Escape
  useEffect(() => {
    if (!open) return
    function onPointer(event: PointerEvent) {
      if (!picker.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('pointerdown', onPointer)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  function submit(event: { preventDefault(): void }) {
    event.preventDefault()
    const request = text.trim()
    if (!request || busy) return
    setText('')
    onSend(request)
  }

  function sendOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  function choose(name: string) {
    onModel(name)
    setOpen(false)
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        aria-label="La tua richiesta"
        placeholder="Chiedi qualcosa, o cerca tra le tue foto"
        rows={1}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={sendOnEnter}
      />
      <div className="composer-bar">
        <div className="picker" ref={picker}>
          <button type="button" className="pill" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
            <icons.Spark />
            {model === 'auto' ? 'Automatico' : model}
            <icons.Down />
          </button>
          {open && (
            <ul className="menu" role="listbox" aria-label="Chi risponde">
              <li>
                <button type="button" role="option" aria-selected={model === 'auto'} onClick={() => choose('auto')}>
                  <b>
                    Automatico {model === 'auto' && <icons.Check />}
                  </b>
                  <span>
                    {automatic ? `Sceglie Regista: adesso ${automatic}, il più adatto a questo computer.` : 'Sceglie Regista.'}
                  </span>
                </button>
              </li>
              {choices.map((choice) => (
                <li key={choice.name}>
                  <button type="button" role="option" aria-selected={model === choice.name} onClick={() => choose(choice.name)}>
                    <b>
                      {choice.name} {model === choice.name && <icons.Check />}
                    </b>
                    <span>
                      {purposes(choice).join(', ')} · {placement(choice).label}
                    </span>
                  </button>
                </li>
              ))}
              {choices.length === 0 && <li className="none">Nessun modello locale trovato.</li>}
            </ul>
          )}
        </div>
        {busy ? (
          <button type="button" className="round ghost" aria-label="Ferma" onClick={onStop}>
            <icons.Stop />
          </button>
        ) : (
          <button type="submit" className="round" aria-label="Invia" disabled={!text.trim()}>
            <icons.Send />
          </button>
        )}
      </div>
    </form>
  )
}
