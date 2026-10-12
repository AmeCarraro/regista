import { expect, test } from 'vitest'
import type { ChatEvent, ModelInfo, Models } from './api.ts'
import { apply, lapse, missing, newReply, placement, purposes, selection, settle, shortGpu, tail, talkers, toMessages, waiting, yesOrNo } from './chat.ts'
import type { Proposed, Turn } from './chat.ts'

function play(events: ChatEvent[]) {
  return events.reduce(apply, newReply(2))
}

const found = { description: 'a black dog', sure: [{ id: 'a', name: 'a.jpg', score: 0.3 }], maybe: [], matching: 1, indexed: 200, partial: false }

/** A reply that proposes to throw away two pictures, as the service sends it. */
function proposing(action: 'trash' | 'copy' = 'trash', folder = '') {
  return play([
    { type: 'text', text: 'Sposto nel cestino queste 2 foto?' },
    { type: 'proposal', action, folder, photos: [{ id: 'a', name: 'a.jpg' }, { id: 'b', name: 'b.jpg' }] },
    { type: 'done', model: 'm', seconds: 1, memory: 'Proposed to move them to the trash (2 photos). Nothing was done: the user must confirm.' },
  ])
}

function proposalOf(turn: Turn): Proposed {
  const part = turn.role === 'assistant' ? turn.parts.find((one) => one.kind === 'proposal') : undefined
  if (part?.kind !== 'proposal') throw new Error('no proposal in this turn')
  return part
}

test('words that arrive one after the other become one piece of text', () => {
  const reply = play([
    { type: 'start', director: 'granite4.1:3b', writer: 'granite4.1:3b', loading: true },
    { type: 'text', text: 'Sto ' },
    { type: 'text', text: 'bene.' },
  ])

  expect(reply.parts).toEqual([{ kind: 'text', text: 'Sto bene.' }])
  expect(reply.status).toBe('writing')
  // the first word means the model is in memory: the "loading" notice goes away
  expect(reply.loading).toBe(false)
})

test('a search shows what was looked for, then the pictures, then what the app says about them', () => {
  const reply = play([
    { type: 'start', director: 'granite4.1:3b', writer: 'granite4.1:3b', loading: false },
    { type: 'step', tool: 'find_photos', arguments: { description: 'a black dog' } },
    { type: 'photos', ...found },
    { type: 'text', text: 'Ho trovato 1 foto.' },
    { type: 'done', model: 'granite4.1:3b', seconds: 4.2, memory: 'Searched the photos for "a black dog": 1 found, 0 uncertain.' },
  ])

  expect(reply.parts.map((part) => part.kind)).toEqual(['search', 'photos', 'text'])
  expect(reply.parts[0]).toEqual({ kind: 'search', description: 'a black dog', place: 'computer', period: '', spot: '' })
  expect(reply.status).toBe('done')
  expect(reply.seconds).toBe(4.2)
})

test('the model is told what to remember of a reply, not what was shown', () => {
  const reply = play([
    { type: 'step', tool: 'find_photos', arguments: { description: 'a dog' } },
    { type: 'photos', ...found },
    { type: 'text', text: 'Ho trovato 1 foto.' },
    { type: 'done', model: 'm', seconds: 1, memory: 'Searched the photos for "a dog": 1 found, 0 uncertain.' },
  ])
  const turns: Turn[] = [{ id: 1, role: 'user', text: 'trovami un cane' }, reply, { id: 3, role: 'user', text: 'solo quelli neri' }]

  expect(toMessages(turns)).toEqual([
    { role: 'user', content: 'trovami un cane' },
    { role: 'assistant', content: 'Searched the photos for "a dog": 1 found, 0 uncertain.' },
    { role: 'user', content: 'solo quelli neri' },
  ])
})

test('a reply that was stopped keeps the words it had, and one that said nothing is left out', () => {
  const stopped = { ...play([{ type: 'text', text: 'Il Giappone è' }]), status: 'stopped' as const }
  const failed = play([{ type: 'error', message: 'Ollama is down' }])
  const turns: Turn[] = [{ id: 1, role: 'user', text: 'a' }, stopped, { id: 3, role: 'user', text: 'b' }, { ...failed, id: 4 }]

  expect(failed.status).toBe('error')
  expect(toMessages(turns).map((message) => message.content)).toEqual(['a', 'Il Giappone è', 'b'])
})

test('a proposal waits for an answer, with every picture ticked', () => {
  const reply = proposing()
  const turns: Turn[] = [{ id: 1, role: 'user', text: 'eliminale' }, reply]

  expect(reply.parts.map((part) => part.kind)).toEqual(['text', 'proposal'])
  expect(proposalOf(reply)).toMatchObject({ state: 'asked', picked: ['a', 'b'], folder: '', entry: '' })
  expect(waiting(turns)?.reply.id).toBe(2)
  expect(waiting([turns[0]])).toBeNull()
})

test('what became of a proposal is remembered next to what was proposed', () => {
  const done = settle(proposing(), { state: 'done', note: 'Fatto: 2 foto nel cestino.', entry: 'e1' }, 'The user confirmed: 2 photos were moved to the trash.')
  const turns: Turn[] = [{ id: 1, role: 'user', text: 'eliminale' }, done]

  expect(proposalOf(done)).toMatchObject({ state: 'done', entry: 'e1', picked: ['a', 'b'] })
  expect(waiting(turns)).toBeNull()
  expect(toMessages(turns)[1].content).toBe(
    'Proposed to move them to the trash (2 photos). Nothing was done: the user must confirm.\nThe user confirmed: 2 photos were moved to the trash.',
  )
  // a change that says nothing new leaves the memory as it was
  expect(settle(done, { picked: ['a'] }).memory).toBe(done.memory)
})

test('a proposal left without an answer lapses when the conversation moves on', () => {
  const turns: Turn[] = [{ id: 1, role: 'user', text: 'eliminale' }, proposing()]

  const after = lapse(turns)

  expect(proposalOf(after[1]).state).toBe('declined')
  expect(toMessages(after)[1].content).toMatch(/The user did not confirm: nothing was changed\.$/)
  expect(waiting(after)).toBeNull()
  // with nothing waiting, nothing changes
  expect(lapse(after)).toBe(after)
})

test('a plain yes or no is recognised, and anything else is a new request', () => {
  for (const yes of ['sì', 'Sì.', 'si', 'Si, procedi!', 'ok', 'Va bene', 'confermo', "D’accordo", 'ok, grazie']) expect(yesOrNo(yes), yes).toBe('yes')
  for (const no of ['no', 'No.', 'annulla', 'lascia stare', 'No, grazie', 'non farlo']) expect(yesOrNo(no), no).toBe('no')
  for (const other of ['sì ma togli la prima', 'eliminale', 'si chiama Cani', 'no aspetta, cercami i gatti', 'ok cerca i gatti', ''])
    expect(yesOrNo(other), other).toBeNull()
})

test('a proposal says what stops it from being carried out', () => {
  const trash = proposalOf(proposing())
  const copy = proposalOf(proposing('copy'))
  const undo = proposalOf(play([{ type: 'proposal', action: 'undo', of: 'e1', undoes: 'trash', folder: '', count: 2, when: '2026-10-11T15:00:00+02:00' }]))

  expect(missing(trash)).toBe('')
  expect(missing({ ...trash, picked: [] })).toMatch(/nessuna foto/)
  expect(missing(copy)).toMatch(/nome della cartella/)
  expect(missing({ ...copy, folder: '  ' })).toMatch(/nome della cartella/)
  expect(missing({ ...copy, folder: 'Cani' })).toBe('')
  expect(missing(undo)).toBe('')
  expect(undo.picked).toEqual([])
})

test('"these" are the pictures of the last search that are still there', () => {
  const dogs = play([{ type: 'photos', ...found, sure: [{ id: 'a', name: 'a.jpg', score: 0.3 }, { id: 'b', name: 'b.jpg', score: 0.3 }], maybe: [{ id: 'c', name: 'c.jpg', score: 0.22 }] }])
  const unsure = { ...play([{ type: 'photos', ...found, sure: [], maybe: [{ id: 'x', name: 'x.jpg', score: 0.22 }] }]), id: 4 }
  const talk = { ...play([{ type: 'text', text: 'Ciao.' }]), id: 6 }

  expect(selection([dogs])).toEqual(['a', 'b'])
  expect(selection([dogs], new Set(['a']))).toEqual(['b'])
  // only the last search counts, and words in between do not hide it
  expect(selection([dogs, unsure, talk])).toEqual(['x'])
  expect(selection([talk])).toEqual([])
  // pictures shown in a proposal count too: the ones left ticked
  expect(selection([dogs, { ...settle(proposing('copy', 'Cani'), { picked: ['b'] }), id: 8 }])).toEqual(['b'])
})

test('the page follows the end of the conversation, not what changes further up', () => {
  const reply = proposing()
  const turns: Turn[] = [{ id: 1, role: 'user', text: 'eliminale' }, reply]

  expect(tail([turns[0], settle(reply, { picked: ['a'] })])).toBe(tail(turns))
  expect(tail([...turns, { id: 3, role: 'user', text: 'sì' }])).not.toBe(tail(turns))
  expect(tail([turns[0], apply(reply, { type: 'text', text: ' E poi?' })])).not.toBe(tail(turns))
})

const model = (name: string, change: Partial<ModelInfo> = {}): ModelInfo => ({
  name,
  gigabytes: 2.1,
  parameters: '3.4B',
  can: ['tools', 'chat'],
  where: 'gpu',
  loaded: false,
  tested: null,
  ...change,
})

test('a model is described by what it is for and by where it runs', () => {
  expect(purposes(model('a'))).toEqual(['usa gli strumenti', 'risponde a parole'])
  expect(purposes(model('eyes', { can: ['chat', 'vision'] }))).toEqual(['risponde a parole', 'guarda le immagini'])
  expect(placement(model('a'))).toEqual({ label: 'tutto sulla scheda video', good: true })
  expect(placement(model('big', { where: 'split' })).good).toBe(false)
  expect(placement(model('small', { where: 'cpu' })).good).toBe(true)
})

test('the models offered for talking come in the order the app prefers', () => {
  const models: Models = {
    hardware: { gpu: '', gpu_gb: 0, ram_gb: 8, cores: 4 },
    models: [model('b'), model('embed', { can: [] }), model('a')],
    order: { tools: ['a'], chat: ['a', 'b'], vision: [] },
    suggested: null,
  }

  expect(talkers(models).map((entry) => entry.name)).toEqual(['a', 'b'])
})

test('the name of the graphics card is shortened to its model', () => {
  expect(shortGpu('NVIDIA GeForce RTX 3050 Ti Laptop GPU')).toBe('RTX 3050 Ti')
})
