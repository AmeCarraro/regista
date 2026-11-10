import { useEffect, useRef, useState } from 'react'
import * as icons from '../icons.tsx'
import { cancelCommandSpeech, commandPreviewAvailable, commandSpeech, commandSpeechAvailable, commandTagsAvailable, findCommandTagged, listenCommand, previewCommand } from './bridge.ts'
import type { CommandPreview as Preview, CommandSpeech } from './bridge.ts'
import CommandMusic from './CommandMusic.tsx'
import CommandTags from './CommandTags.tsx'
import type { TagCommand } from './CommandTags.tsx'
import type { Picture } from './select.ts'

const ACTIONS = {
  search_photos: 'Ricerca di foto per tag',
  add_tag: 'Aggiunta di un tag',
  remove_tag: 'Rimozione di un tag',
  play_song: 'Riproduzione di un brano',
  clarify: 'Serve un chiarimento',
}

const MAX_LENGTH = 500

export default function CommandPreview({ pictures, thumb }: { pictures: Picture[]; thumb: (id: string) => string }) {
  const [available] = useState(commandPreviewAvailable)
  const [canTag] = useState(commandTagsAvailable)
  const [text, setText] = useState('')
  const [result, setResult] = useState<{ preview: Preview; tags: TagCommand | null; attempt: number } | null>(null)
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
          setSpeech({ status: 'error', error: 'Riprova con un comando più breve o scrivilo.' })
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

  function interpret(request: string) {
    const preview = previewCommand(request)
    let tags: TagCommand | null = null
    if (canTag && !('error' in preview) && preview.slots.tag) {
      if (preview.intent === 'search_photos') {
        tags = { search: findCommandTagged(preview.slots.tag) }
      } else if (preview.intent === 'add_tag' || preview.intent === 'remove_tag') {
        tags = { action: preview.intent, tag: preview.slots.tag }
      }
    }
    setResult((before) => ({ preview, tags, attempt: (before?.attempt ?? 0) + 1 }))
  }

  if (!available) return null
  const preview = result?.preview

  return (
    <details className="card command-preview" onToggle={(event) => {
      if (!event.currentTarget.open) {
        stopListening()
        setResult(null)
      }
    }}>
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
          interpret(request)
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
        {speech.status === 'error' && <p>{speech.error}</p>}
        {preview && ('error' in preview ? (
          <p>{preview.error}</p>
        ) : (
          <>
            <p><strong>{ACTIONS[preview.intent]}</strong></p>
            {preview.slots.tag && <p>Tag «{preview.slots.tag}»</p>}
            {preview.slots.title && <p>Brano «{preview.slots.title}»</p>}
            {preview.slots.artist && <p>Artista «{preview.slots.artist}»</p>}
          </>
        ))}
      </div>
      {result?.tags && <CommandTags key={result.attempt} command={result.tags} pictures={pictures} thumb={thumb} />}
      {preview && !('error' in preview) && preview.intent === 'play_song' && preview.slots.title && (
        <CommandMusic key={result?.attempt} title={preview.slots.title} artist={preview.slots.artist} />
      )}
    </details>
  )
}
