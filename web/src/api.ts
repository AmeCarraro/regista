// The contract with the service (app/main.py), written as types: the compiler then
// checks that the page handles every kind of event the service can send.

/** A job a model can be given: decide and use tools, talk, look at a picture. */
export type Job = 'tools' | 'chat' | 'vision'

/** How a model did when it was tried on this computer. */
export type Tested = {
  cases: number
  right: number
  tokens_per_second: number
  gpu_share: number | null
  tested_on: string
}

export type ModelInfo = {
  name: string
  gigabytes: number
  parameters: string
  can: Job[]
  /** Where it would run here: all in video memory, split with the processor, on the processor, or too large. */
  where: 'gpu' | 'split' | 'cpu' | 'heavy'
  loaded: boolean
  tested: Tested | null
}

/** The model worth having on this computer for the job of director, installed or not. */
export type Suggested = {
  name: string
  /** The size of the download. */
  gigabytes: number
  /** Where it would run here: see ModelInfo. */
  where: 'gpu' | 'split' | 'cpu'
  installed: boolean
  /** What to type in a terminal to get it: the app does not download models by itself. */
  command: string
}

export type Models = {
  // unproven_gb: the memory of a card that is there, but that no model was seen running on yet
  hardware: { gpu: string; gpu_gb: number; ram_gb: number; cores: number; unproven_gb: number }
  models: ModelInfo[]
  /** For every job, the names of the models that can do it, best first. */
  order: Record<Job, string[]>
  /** Null when the computer was not measured, or is too small for any model the app knows. */
  suggested: Suggested | null
  /** Set when the local models could not be reached. */
  problem?: string
}

/** A picture found; `day` is the day it was taken, as "2024-08-15", empty when not known. */
export type Photo = { id: string; name: string; score: number; day?: string }

export type Found = {
  description: string
  sure: Photo[]
  maybe: Photo[]
  /** How many sure matches there are in all: it can be more than the ones sent. */
  matching: number
  indexed: number
  partial: boolean
  /** Where the pictures are: on this computer, or on a phone that sent small copies of them. */
  place?: Place
  /** When the pictures are looked at one by one: how many there are to look at, and how many were looked at. */
  checking?: number
  looked?: number
}

export type Place = 'computer' | 'phone'

/** A picture named in a proposal: its short name, and the name of its file. */
export type Picked = { id: string; name: string }

/** An album of a trip: the folder it goes into, and its pictures by their short names. */
export type Album = { folder: string; ids: string[] }

/**
 * A change to the pictures that the app proposes. It is carried out only when
 * the user says yes, by the page, with carryOut or takeBack below.
 */
export type Proposal =
  // "fetch" copies pictures from a phone to this computer: the phone sends them when its app is open.
  // "clear" does the same and then has the phone move them to its own trash, after a yes given there.
  // "send" prepares pictures of this computer for the phone, which takes them into an album.
  | { action: 'trash' | 'copy' | 'move' | 'fetch' | 'clear' | 'send'; folder: string; photos: Picked[] }
  // a copy of the pictures of each trip into an album of its own; `photos` are all of them
  | { action: 'albums'; folder: string; photos: Picked[]; albums: Album[] }
  // "receive" is what a fetch becomes in the journal once the pictures have arrived
  | { action: 'undo'; of: string; undoes: 'trash' | 'copy' | 'move' | 'receive' | 'albums'; folder: string; count: number; when: string }

/** The events of POST /api/chat, one JSON object per line. */
export type ChatEvent =
  | { type: 'start'; director: string | null; writer: string; loading: boolean }
  | { type: 'text'; text: string }
  | { type: 'step'; tool: string; arguments: Record<string, unknown> }
  | ({ type: 'photos' } & Found)
  // a picture confirmed by the model that looks at them, as soon as it is
  | { type: 'photo'; photo: Photo }
  // how far the looking is; when looked and of are the same, it is over
  | { type: 'looked'; looked: number; of: number }
  | ({ type: 'proposal' } & Proposal)
  | { type: 'done'; model: string; seconds: number; tokens_per_second?: number; memory: string }
  | { type: 'error'; message: string }

/** What a change did, once carried out: in numbers, and in the words to show. */
export type Outcome = {
  kind: 'trash' | 'copy' | 'move' | 'fetch' | 'clear' | 'send' | 'albums' | 'undo'
  /** The name of the change, to take it back later. Empty when nothing was touched, or for an undo. */
  id: string
  count: number
  /** The pictures that left the library (trash) or came back to it (undo). */
  ids: string[]
  folder: string
  text: string
  /** What the model should remember of it. */
  memory: string
  /** For a fetch: the name of the request to the phone, to follow until the pictures arrive. */
  transfer?: string
}

/** How far a request to a phone is. */
export type Transfer = {
  id: string
  /** "confirming": the pictures are here, and the phone is asking its user whether they may go to its trash. */
  state: 'waiting' | 'confirming' | 'done'
  arrived: number
  total: number
  folder: string
  /** The name of the arrival among the changes, to take it back; empty until done, if nothing arrived, or if the pictures left the phone. */
  entry: string
  /** The pictures that are no longer on the phone. */
  gone: string[]
  text: string
  memory: string
}

/** A phone that was let in. */
export type Device = {
  id: string
  name: string
  paired: string
  /** When it last talked to this computer. */
  seen: string
  /** How many of its pictures this computer knows. */
  photos: number
  /** How many pictures it has been asked for and has not sent yet. */
  waiting: number
}

/** A phone that showed a good code and waits for the yes here: the name it gives itself, and the number it shows. */
export type Pending = { id: string; name: string; code: string; seconds: number }

export type PhoneState = {
  /** Whether the door of the phones was opened to the network when the app was started. */
  open: boolean
  addresses: string[]
  devices: Device[]
  pending: Pending[]
  /** The knocks at the door of the phones that were refused since the app started: how many, the last one, and what was wrong. */
  refused: { count: number; last: string; what: string }
}

/** What lets one phone in: a link, and the same link as a QR code (a picture, ready to be the source of an image). */
export type Invite = { link: string; seconds: number; qr: string }

/** What can be changed, and what was: the answer of GET /api/actions. */
export type Changes = {
  /** False when the picture folder was given to the app to read only. */
  writable: boolean
  /** How many files are in the app's trash. */
  trash: number
  last: { id: string; kind: 'trash' | 'copy' | 'move' | 'receive' | 'albums'; count: number; folder: string; when: string } | null
}

/** The events of POST /api/models/test. */
export type TestEvent =
  | { type: 'progress'; model: string; case: number; cases: number }
  | ({ type: 'result'; model: string } & Tested)
  | { type: 'problem'; model: string; message: string }
  | { type: 'done'; tests: Record<string, Tested> }
  | { type: 'error'; message: string }

export type Library = {
  running: boolean
  done: number
  total: number
  error: string
  indexed: number
  folder: string
  /** Which door the page came through: this computer's, or the one of the phones (inside a phone's app). */
  door: 'computer' | 'phone'
}

export type Message = { role: 'user' | 'assistant'; content: string }

/**
 * Turns a stream of bytes into the JSON values it carries, one per line.
 * A chunk can end in the middle of a line, or even of a character, so the
 * unfinished tail is kept and completed by the next chunk.
 */
export async function* jsonLines<T>(chunks: AsyncIterable<Uint8Array>): AsyncGenerator<T> {
  const decoder = new TextDecoder()
  let pending = ''
  for await (const chunk of chunks) {
    pending += decoder.decode(chunk, { stream: true })
    const lines = pending.split('\n')
    pending = lines.pop() ?? ''
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line) as T
    }
  }
  pending += decoder.decode()
  if (pending.trim()) yield JSON.parse(pending) as T
}

async function* chunksOf(body: ReadableStream<Uint8Array>): AsyncGenerator<Uint8Array> {
  const reader = body.getReader()
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) return
      yield value
    }
  } finally {
    reader.releaseLock()
  }
}

async function* stream<T>(path: string, body: unknown, signal: AbortSignal): AsyncGenerator<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) throw new Error(`Il servizio ha risposto ${response.status}`)
  yield* jsonLines<T>(chunksOf(response.body))
}

/**
 * Sends the conversation and yields the reply as it happens. Aborting `signal` stops the model too.
 * `selection` is the pictures on screen: what "these" means in the request.
 */
export function chatStream(messages: Message[], model: string, selection: string[], signal: AbortSignal): AsyncGenerator<ChatEvent> {
  return stream<ChatEvent>('/api/chat', { messages, model, selection }, signal)
}

/** Tries the models on this computer and yields the progress. */
export function testModels(signal: AbortSignal): AsyncGenerator<TestEvent> {
  return stream<TestEvent>('/api/models/test', {}, signal)
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Il servizio ha risposto ${response.status}`)
  return (await response.json()) as T
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const answer: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    // when the service refuses, it says why in words meant for the user
    const detail = (answer as { detail?: unknown } | null)?.detail
    throw new Error(typeof detail === 'string' ? detail : `Il servizio ha risposto ${response.status}`)
  }
  return answer as T
}

export const fetchModels = () => get<Models>('/api/models')

export const fetchLibrary = () => get<Library>('/api/photos')

export const fetchChanges = () => get<Changes>('/api/actions')

/** Carries out a change the user said yes to. Nothing else in the page changes a picture. */
export const carryOut = (action: 'trash' | 'copy' | 'move' | 'fetch' | 'clear' | 'send', ids: string[], folder: string) =>
  post<Outcome>('/api/actions', { action, ids, folder })

/** Copies the pictures of each trip into its album, all at once: one change, taken back as one. */
export const makeAlbums = (albums: Album[]) => post<Outcome>('/api/actions/albums', { albums })

export const fetchTransfer = (id: string) => get<Transfer>(`/api/transfers/${id}`)

export const fetchPhone = () => get<PhoneState>('/api/phone')

export const invitePhone = () => post<Invite>('/api/phone/invite', {})

export const forgetPhone = (id: string) => post<{ forgotten: boolean }>(`/api/phone/devices/${id}/forget`, {})

/** The answer, given here, to a phone that asks to come in. */
export const answerPhone = (id: string, yes: boolean) => post<{ answered: boolean }>(`/api/phone/pending/${id}`, { yes })

/** Takes back a change, named by the id its outcome carried. */
export const takeBack = (of: string) => post<Outcome>('/api/actions/undo', { of })

export const readFolderAgain = () => fetch('/api/photos/read', { method: 'POST' })

export const thumbOf = (id: string) => `/api/photos/${id}/thumb`

export const fullOf = (id: string) => `/api/photos/${id}/full`
