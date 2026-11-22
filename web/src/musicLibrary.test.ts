import { describe, expect, it } from 'vitest'
import { musicMatches, musicTags } from './musicLibrary.ts'
import type { MusicLibrary } from './musicLibrary.ts'

describe('music collections', () => {
  const tracks = [
    { id: 'jaz', title: 'Estate', artist: 'Bruno Martino', album: '', genre: 'Jazz' },
    { id: 'pop', title: 'Estate lenta', artist: '', album: '', genre: 'Pop' },
    { id: 'new', title: 'Autunno', artist: '', album: '', genre: 'Jazz' },
  ]
  const rules: MusicLibrary = {
    tags: { jaz: ['Sera', 'Jazz'], pop: ['sera'] },
    playlists: { jazz: { name: 'Jazz', query: '', tag: 'Jazz' } },
  }

  it('uses embedded and manual tags together without duplicates', () => {
    expect(musicTags(tracks, rules)).toEqual(['Jazz', 'Pop', 'sera'])
    expect(musicMatches(tracks, rules, 'Estate', 'SERA').map((track) => track.id)).toEqual(['jaz', 'pop'])
  })

  it('includes newly added music which matches a saved playlist', () => {
    const playlist = rules.playlists.jazz
    expect(musicMatches(tracks, rules, playlist.query, playlist.tag).map((track) => track.id)).toEqual(['jaz', 'new'])
  })
})
