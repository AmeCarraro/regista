import { useState } from 'react'
import type { MusicLibrary, Playlist } from './musicLibrary.ts'
import './music-library.css'

type Props = {
  library: MusicLibrary
  tags: string[]
  query: string
  tag: string
  selected: string
  onTag: (tag: string) => void
  onPlaylist: (key: string) => void
  onSave: (playlist: Playlist) => Promise<void>
}

export function MusicFilters({ library, tags, query, tag, selected, onTag, onPlaylist, onSave }: Props) {
  const [name, setName] = useState<string | null>(null)
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)
  const playlists = Object.entries(library.playlists).sort(([, a], [, b]) => a.name.localeCompare(b.name, 'it'))

  async function save() {
    if (!name?.trim()) return
    setSaving(true)
    setProblem('')
    try {
      await onSave({ name: name.trim(), query: query.trim(), tag })
      setName(null)
    } catch (error) {
      setProblem(String(error instanceof Error ? error.message : error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="music-filters">
      <select aria-label="Genere o tag" value={tag} onChange={(event) => onTag(event.target.value)}>
        <option value="">Tutti i generi e tag</option>
        {tag && !tags.includes(tag) && <option value={tag}>{tag}</option>}
        {tags.map((label) => <option key={label} value={label}>{label}</option>)}
      </select>
      {playlists.length > 0 && (
        <select aria-label="Playlist" value={selected} onChange={(event) => onPlaylist(event.target.value)}>
          <option value="">Tutti i brani</option>
          {playlists.map(([key, { name }]) => <option key={key} value={key}>{name}</option>)}
        </select>
      )}
      {name === null ? (
        <button type="button" className="library-button" disabled={!tag && !query.trim()} onClick={() => setName(library.playlists[selected]?.name ?? '')}>
          Salva playlist
        </button>
      ) : (
        <form className="music-label-form" onSubmit={(event) => { event.preventDefault(); void save() }}>
          <input aria-label="Nome playlist" placeholder="Nome playlist" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} />
          <button type="submit" className="library-button" disabled={!name.trim() || saving || (!tag && !query.trim())}>Salva</button>
          <button type="button" className="library-button" onClick={() => { setName(null); setProblem('') }}>Annulla</button>
        </form>
      )}
      {problem && <small className="music-feedback" role="alert">{problem}</small>}
    </div>
  )
}

export function SongTagEditor({ tags, onSave, onClose }: { tags: string[]; onSave: (tags: string) => Promise<void>; onClose: () => void }) {
  const [draft, setDraft] = useState(tags.join(', '))
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    setProblem('')
    try {
      await onSave(draft)
      onClose()
    } catch (error) {
      setProblem(String(error instanceof Error ? error.message : error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="music-label-form" onSubmit={(event) => { event.preventDefault(); void save() }}>
      <input aria-label="Tag del brano" placeholder="Tag separati da virgole" value={draft} maxLength={1200} onChange={(event) => setDraft(event.target.value)} />
      <button type="submit" className="library-button" disabled={saving}>Salva tag</button>
      <button type="button" className="library-button" onClick={onClose}>Annulla</button>
      {problem && <small className="music-feedback" role="alert">{problem}</small>}
    </form>
  )
}
