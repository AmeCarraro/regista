import { expect, test } from 'vitest'
import { addedInWords } from './added.ts'

const nothing = { busy: false, total: 0, done: 0, skipped: 0, failed: 0 }

test('before the first time it says where songs can come from', () => {
  expect(addedInWords(nothing)).toBe('Da qualsiasi cartella del telefono, anche da WhatsApp.')
})

test('while it copies it says how far it is', () => {
  expect(addedInWords({ ...nothing, busy: true, total: 5 })).toBe('Copio le canzoni nella musica: 1 di 5…')
  expect(addedInWords({ ...nothing, busy: true, total: 5, done: 3, skipped: 1 })).toBe('Copio le canzoni nella musica: 5 di 5…')
})

test('after, it says how it went', () => {
  expect(addedInWords({ ...nothing, total: 1, done: 1 })).toBe('Aggiunta una canzone.')
  expect(addedInWords({ ...nothing, total: 4, done: 3, skipped: 1 })).toBe("Aggiunte 3 canzoni, una c'era già.")
  expect(addedInWords({ ...nothing, total: 5, done: 2, skipped: 2, failed: 1 })).toBe("Aggiunte 2 canzoni, 2 c'erano già, una non sono riuscito a copiarla.")
  expect(addedInWords({ ...nothing, total: 3, skipped: 1, failed: 2 })).toBe("Una c'era già, 2 non sono riuscito a copiarle.")
  expect(addedInWords({ ...nothing, total: 1, skipped: 1 })).toBe("La canzone c'era già.")
  expect(addedInWords({ ...nothing, total: 3, skipped: 3 })).toBe("Le canzoni c'erano già tutte.")
  expect(addedInWords({ ...nothing, total: 2, failed: 2 })).toBe('Non sono riuscito a copiare le canzoni.')
})
