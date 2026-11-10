import { useEffect, useRef, useState } from 'react'
import * as icons from '../icons.tsx'
import { cancelCommandSpeech, commandPreviewAvailable, commandSpeech, commandSpeechAvailable, listenCommand, previewCommand } from './bridge.ts'
import type { CommandPreview as Preview, CommandSpeech } from './bridge.ts'

const ACTIONS = {
  search_photos: 'Ricerca di foto per tag',
  add_tag: 'Aggiunta di un tag',
  remove_tag: 'Rimozione di un tag',
  play_song: 'Riproduzione di un brano',
  clarify: 'Serve un chiarimento',
}

const MAX_LENGTH = 500

export default function CommandPreview() {
  const [available] = useState(commandPreviewAvailable)
  const [text, setText] = useState('')
  const [result, setResult] = useState<Preview | null>(null)
  const [canListen, setCanListen] = useState(commandSpeechAvailable)
  const [speech, setSpeech] = useState<CommandSpeech>({ status: 'idle' })
  const hearing = useRef(false)
  const listening = speech.status === 'listening'

  useEffect(() => {
    if (!available) return
    function update() {
      setCanListen(commandSpeechAvailable())
      if (!hearing.current) return
      const next = commandSpeech()
      if (next.status !== 'listening') hearing.current = false
      if (next.status === 'result') {
        const words = next.text.trim()
        if (!words || words.length > MAX_LENGTH) {
          setSpeech({ status: 'error', error: 'Riprova con un comando più breve.' })
          return
        }
        setText(words)
        setResult(null)
      }
      setSpeech(next)
    }
    window.registaCommandSpeech = update
    update()
    return () => {
      delete window.registaCommandSpeech
      if (hearing.current) {
        hearing.current = false
        cancelCommandSpeech()
      }
    }
  }, [available])

  function stopListening() {
    if (!hearing.current) return
    hearing.current = false
    setSpeech({ status: 'idle' })
    cancelCommandSpeech()
  }

  function startListening() {
    hearing.current = true
    setSpeech({ status: 'listening' })
    setResult(null)
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    listenCommand()
  }

  if (!available) return null

  return (
    <details className="card command-preview" onToggle={(event) => { if (!event.currentTarget.open) stopListening() }}>
      <summary>Prova comandi offline</summary>
      <p>{canListen ? 'Scrivi o detta' : 'Scrivi'} una richiesta per vedere l’azione e i nomi che riconosce il modello sul telefono.</p>
      {(canListen || listening) && (
        <button type="button" className="quiet" onClick={listening ? stopListening : startListening}>
          {listening ? 'Annulla ascolto' : 'Detta il comando'}
        </button>
      )}
      <form
        className="ask"
        onSubmit={(event) => {
          event.preventDefault()
          const request = text.trim()
          if (!request || listening) return
          setResult(previewCommand(request))
          if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
        }}
      >
        <input
          aria-label="Comando da provare"
          value={text}
          onChange={(event) => {
            setText(event.target.value)
            setResult(null)
            setSpeech({ status: 'idle' })
          }}
          placeholder="Mostrami le foto dei cani"
          maxLength={MAX_LENGTH}
          disabled={listening}
          enterKeyHint="go"
          autoComplete="off"
        />
        <button type="submit" className="go" disabled={listening || !text.trim()} aria-label="Prova il comando">
          <icons.Arrow />
        </button>
      </form>
      <div role="status">
        {listening && <p>In ascolto…</p>}
        {speech.status === 'result' && <p>Trascrizione pronta. Puoi correggerla prima di provare il comando.</p>}
        {speech.status === 'error' && <p>{speech.error} Puoi scrivere il comando.</p>}
        {result && ('error' in result ? (
          <p>{result.error}</p>
        ) : (
          <>
            <p><strong>{ACTIONS[result.intent]}</strong></p>
            {result.slots.tag && <p>Tag «{result.slots.tag}»</p>}
            {result.slots.title && <p>Brano «{result.slots.title}»</p>}
            {result.slots.artist && <p>Artista «{result.slots.artist}»</p>}
          </>
        ))}
      </div>
    </details>
  )
}
