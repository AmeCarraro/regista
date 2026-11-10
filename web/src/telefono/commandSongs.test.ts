import { describe, expect, it } from 'vitest'
import { commandSongs } from './commandSongs.ts'

const songs = [
  { id: '1', title: 'Imagine', artist: 'John Lennon' },
  { id: '2', title: 'Imagine', artist: 'Eva Cassidy' },
  { id: '3', title: 'Imagine (Live)', artist: 'John Lennon' },
  { id: '4', title: 'L’ottavo giorno', artist: 'Max Gazzè' },
  { id: '5', title: 'Sì', artist: 'Due' },
  { id: '6', title: 'Si', artist: 'Due' },
]

describe('commandSongs', () => {
  it('keeps exact-title alternatives for an explicit choice', () => {
    expect(commandSongs(songs, ' IMAGINE ').map((song) => song.id)).toEqual(['1', '2'])
  })

  it('requires the full artist when provided, without title-only fallback', () => {
    expect(commandSongs(songs, 'Imagine', '  JOHN  LENNON ')).toEqual([songs[0]])
    expect(commandSongs(songs, 'Imagine', 'Lennon')).toEqual([])
    expect(commandSongs(songs, 'Imagine', ' ')).toEqual([])
    expect(commandSongs(songs, 'Imag', 'John Lennon')).toEqual([])
    expect(commandSongs(songs, '')).toEqual([])
  })

  it('accepts equivalent accents and apostrophes while preserving accent distinctions', () => {
    expect(commandSongs(songs, "L'OTTAVO GIORNO", 'Max Gazze\u0300')).toEqual([songs[3]])
    expect(commandSongs(songs, 'si\u0300', 'Due')).toEqual([songs[4]])
    expect(commandSongs(songs, 'Si', 'Due')).toEqual([songs[5]])
  })
})
