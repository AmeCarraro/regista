import { matching } from './clock.ts'

export type Playlist = { name: string; query: string; tag: string }
export type MusicLibrary = { tags: Record<string, string[]>; playlists: Record<string, Playlist> }
export const EMPTY_LIBRARY: MusicLibrary = { tags: {}, playlists: {} }

type Track = { id: string; artist: string; album: string; title: string; folder?: string; genre?: string }
const tagKey = (name: string) => name.trim().normalize('NFC').toLocaleLowerCase('it')

export function trackTags(track: Track, library: MusicLibrary): string[] {
  const tags = [track.genre ?? '', ...(library.tags[track.id] ?? [])].map((tag) => tag.trim()).filter(Boolean)
  return [...new Map(tags.map((tag) => [tagKey(tag), tag])).values()]
}

export function musicTags(tracks: Track[], library: MusicLibrary): string[] {
  const choices = new Map<string, string>()
  for (const track of tracks) {
    for (const tag of trackTags(track, library)) choices.set(tagKey(tag), tag)
  }
  return [...choices.values()].sort((a, b) => a.localeCompare(b, 'it'))
}

export function musicMatches<T extends Track>(tracks: T[], library: MusicLibrary, query: string, tag: string): T[] {
  const found = matching(tracks, query)
  const wanted = tagKey(tag)
  return wanted ? found.filter((track) => trackTags(track, library).some((label) => tagKey(label) === wanted)) : found
}

export type MusicSyncJob = {
  id: string
  state: 'idle' | 'requested' | 'scanning' | 'copying' | 'ready' | 'error'
  sent: number
  received: number
  to_pc: number
  to_phone: number
  error: string
}

export const IDLE_MUSIC_SYNC: MusicSyncJob = { id: '', state: 'idle', sent: 0, received: 0, to_pc: 0, to_phone: 0, error: '' }

export function musicSyncBusy(job?: MusicSyncJob) {
  return job?.state === 'requested' || job?.state === 'scanning' || job?.state === 'copying'
}

export function musicSyncText(job?: MusicSyncJob) {
  switch (job?.state) {
    case 'requested': return 'Richiesta inviata. Apri Regista sul telefono e consenti l’accesso alla musica.'
    case 'scanning': return 'Confronto i brani sul PC e sul telefono…'
    case 'copying': return `Verso il PC ${job.sent}/${job.to_pc} · verso il telefono ${job.received}/${job.to_phone}`
    case 'ready': return job.sent || job.received
      ? `Aggiunti ${job.sent} al PC e ${job.received} al telefono.`
      : 'I due dispositivi hanno già gli stessi brani.'
    case 'error': return job.error
    default: return ''
  }
}
