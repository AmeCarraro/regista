// What the music tab says next to «Aggiungi canzoni»: where songs can come from, before the first
// time; how far the copying is, while it goes; and how it went, after.

import type { Adding } from './bridge.ts'

export function addedInWords({ busy, total, done, skipped, failed }: Adding): string {
  if (busy) return `Copio le canzoni nella musica: ${Math.min(done + skipped + failed + 1, total)} di ${total}…`
  if (!total) return 'Da qualsiasi cartella del telefono, anche da WhatsApp.'
  if (skipped === total) return total === 1 ? "La canzone c'era già." : "Le canzoni c'erano già tutte."
  if (failed === total) return total === 1 ? 'Non sono riuscito a copiare la canzone.' : 'Non sono riuscito a copiare le canzoni.'
  const parts: string[] = []
  if (done) parts.push(done === 1 ? 'aggiunta una canzone' : `aggiunte ${done} canzoni`)
  if (skipped) parts.push(skipped === 1 ? "una c'era già" : `${skipped} c'erano già`)
  if (failed) parts.push(failed === 1 ? 'una non sono riuscito a copiarla' : `${failed} non sono riuscito a copiarle`)
  const said = parts.join(', ')
  return `${said.charAt(0).toUpperCase()}${said.slice(1)}.`
}
