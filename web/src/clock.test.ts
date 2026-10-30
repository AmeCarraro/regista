import { expect, test } from 'vitest'
import { clock, matching } from './clock.ts'

test('a length of time is written as players write it', () => {
  expect(clock(0)).toBe('0:00')
  expect(clock(187_400)).toBe('3:07')
  expect(clock(3_725_000)).toBe('1:02:05')
})

test('a song is found by any of its words, in any order', () => {
  const songs = [
    { title: 'Azzurro', artist: 'Paolo Conte', album: 'Azzurro' },
    { title: 'Se telefonando', artist: 'Mina', album: 'Studio Uno', folder: 'Mina/Studio Uno' },
  ]
  expect(matching(songs, 'conte azz').map((song) => song.title)).toEqual(['Azzurro'])
  expect(matching(songs, 'STUDIO').map((song) => song.title)).toEqual(['Se telefonando'])
  expect(matching(songs, '  ')).toHaveLength(2)
})
