import { useState } from 'react'
import * as icons from '../icons.tsx'
import { commandPreviewAvailable, previewCommand } from './bridge.ts'
import type { CommandPreview as Preview } from './bridge.ts'

const ACTIONS = {
  search_photos: 'Ricerca di foto per tag',
  add_tag: 'Aggiunta di un tag',
  remove_tag: 'Rimozione di un tag',
  play_song: 'Riproduzione di un brano',
  clarify: 'Serve un chiarimento',
}

export default function CommandPreview() {
  const [available] = useState(commandPreviewAvailable)
  const [text, setText] = useState('')
  const [result, setResult] = useState<Preview | null>(null)
  if (!available) return null

  return (
    <details className="card command-preview">
      <summary>Prova comandi offline</summary>
      <p>Scrivi una richiesta per vedere l’azione e i nomi che riconosce il modello sul telefono.</p>
      <form
        className="ask"
        onSubmit={(event) => {
          event.preventDefault()
          const request = text.trim()
          if (!request) return
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
          }}
          placeholder="Mostrami le foto dei cani"
          maxLength={500}
          enterKeyHint="go"
          autoComplete="off"
        />
        <button type="submit" className="go" disabled={!text.trim()} aria-label="Prova il comando">
          <icons.Arrow />
        </button>
      </form>
      <div role="status">
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
