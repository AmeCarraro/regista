// What the chat knows that is not drawing: how the events of a reply become
// what is on screen, and what of a conversation is sent back to the model.
import type { ChatEvent, Found, Job, Message, ModelInfo, Models, Photo, Place, Proposal } from './api.ts'

/**
 * A change the app proposed, and what became of it. It waits ("asked") until
 * the user answers; "working" while it is carried out; "waiting" while a phone
 * has been asked for pictures that have not all arrived; then it is "done",
 * "declined", or "undone" when it was done and then taken back.
 */
export type Proposed = {
  kind: 'proposal'
  proposal: Proposal
  state: 'asked' | 'working' | 'waiting' | 'done' | 'declined' | 'undone'
  /** The pictures still ticked: the user can leave some out before saying yes. */
  picked: string[]
  /** The folder of a copy, as the user may have rewritten it. */
  folder: string
  /** How it ended, in words. */
  note: string
  /** Why the last attempt failed, while it still waits. */
  problem: string
  /** The name of the change once done, to take it back. */
  entry: string
  /** The name of the request to a phone, while its pictures are awaited. */
  transfer: string
}

/** A piece of a reply, in the order it arrived. */
export type Part =
  | { kind: 'text'; text: string }
  // `period` is the days the search looked at and `spot` the place the pictures were taken in, both in words, or nothing;
  // `description` can be empty when only a period or a place was asked for
  | { kind: 'search'; description: string; place: Place; period: string; spot: string }
  | ({ kind: 'photos' } & Found)
  | Proposed

export type Turn =
  | { id: number; role: 'user'; text: string }
  | {
      id: number
      role: 'assistant'
      status: 'waiting' | 'writing' | 'done' | 'stopped' | 'error'
      /** The model that is answering, once the service has said which. */
      model: string
      /** True while the model is being loaded into memory, which can take many seconds. */
      loading: boolean
      parts: Part[]
      /** What the model should remember of this turn; it can differ from what was shown. */
      memory: string
      seconds?: number
      speed?: number
      error?: string
    }

export type Reply = Extract<Turn, { role: 'assistant' }>

export function newReply(id: number): Reply {
  return { id, role: 'assistant', status: 'waiting', model: '', loading: false, parts: [], memory: '' }
}

/** A reply after one more event from the service. */
export function apply(reply: Reply, event: ChatEvent): Reply {
  switch (event.type) {
    case 'start':
      return { ...reply, model: event.director ?? event.writer, loading: event.loading }
    case 'text': {
      const last = reply.parts.at(-1)
      // words that arrive one after the other are one piece of text
      const parts: Part[] =
        last?.kind === 'text'
          ? [...reply.parts.slice(0, -1), { kind: 'text', text: last.text + event.text }]
          : [...reply.parts, { kind: 'text', text: event.text }]
      return { ...reply, status: 'writing', loading: false, parts }
    }
    case 'step':
      return {
        ...reply,
        status: 'writing',
        loading: false,
        // only a search has something to show; other tools speak through the text that follows
        parts:
          event.tool === 'find_photos'
            ? [...reply.parts, { kind: 'search', description: String(event.arguments.description ?? ''), place: event.arguments.place === 'phone' ? 'phone' : 'computer', period: String(event.arguments.period ?? ''), spot: String(event.arguments.spot ?? '') }]
            : reply.parts,
      }
    case 'photos': {
      const { type: _, ...found } = event
      return { ...reply, parts: [...reply.parts, { kind: 'photos', ...found }] }
    }
    case 'photo':
      // into the pictures of the reply, where its day puts it: the newest first
      return withPictures(reply, (found) => ({ ...found, sure: newestFirst([...found.sure, event.photo]), matching: found.matching + 1 }))
    case 'looked':
      return withPictures(reply, (found) => ({ ...found, looked: event.looked, checking: event.of }))
    case 'proposal': {
      const { type: _, ...proposal } = event
      const asked: Proposed = {
        kind: 'proposal',
        proposal,
        state: 'asked',
        // every picture is ticked at first
        picked: proposal.action === 'undo' ? [] : proposal.photos.map((photo) => photo.id),
        folder: proposal.folder,
        note: '',
        problem: '',
        entry: '',
        transfer: '',
      }
      return { ...reply, parts: [...reply.parts, asked] }
    }
    case 'done':
      return {
        ...reply,
        status: 'done',
        loading: false,
        model: event.model || reply.model,
        memory: event.memory,
        seconds: event.seconds,
        speed: event.tokens_per_second,
      }
    case 'error':
      return { ...reply, status: 'error', loading: false, error: event.message }
  }
}

/** The newest first, as a gallery shows them; on the same day by name; a picture with no day at the end. */
export function newestFirst(photos: Photo[]): Photo[] {
  return [...photos].sort((one, other) => (other.day || '').localeCompare(one.day || '') || one.name.localeCompare(other.name))
}

/** A reply with the last pictures it shows changed. */
function withPictures(reply: Reply, change: (found: Found) => Found): Reply {
  const at = reply.parts.findLastIndex((part) => part.kind === 'photos')
  if (at < 0) return reply
  const part = reply.parts[at] as Extract<Part, { kind: 'photos' }>
  const { kind: _, ...found } = part
  const parts = [...reply.parts]
  parts[at] = { kind: 'photos', ...change(found) }
  return { ...reply, parts }
}

function shown(reply: Reply): string {
  return reply.parts.flatMap((part) => (part.kind === 'text' ? [part.text] : [])).join('')
}

/** The conversation as the model gets it: what the user wrote, and what to remember of each reply. */
export function toMessages(turns: Turn[]): Message[] {
  return turns.flatMap((turn): Message[] => {
    if (turn.role === 'user') return [{ role: 'user', content: turn.text }]
    const content = turn.memory || shown(turn)
    // a reply that failed or was stopped before saying anything leaves nothing to remember
    return content ? [{ role: 'assistant', content }] : []
  })
}

/** A mark that changes when the conversation grows at its end, and not when something further up changes. */
export function tail(turns: Turn[]): string {
  const last = turns.at(-1)
  if (last?.role !== 'assistant') return `${turns.length}`
  const end = last.parts.at(-1)
  return `${turns.length}:${last.status}:${last.parts.length}:${end?.kind === 'text' ? end.text.length : 0}`
}

/** The proposal that still waits for an answer, with the reply it belongs to. There is one at most. */
export function waiting(turns: Turn[]): { reply: Reply; proposed: Proposed } | null {
  for (const turn of turns) {
    if (turn.role !== 'assistant') continue
    const proposed = turn.parts.find((part) => part.kind === 'proposal')
    if (proposed?.kind === 'proposal' && proposed.state === 'asked') return { reply: turn, proposed }
  }
  return null
}

/** A reply after its proposal changed, with something more for the model to remember. A reply makes one proposal at most. */
export function settle(reply: Reply, change: Partial<Omit<Proposed, 'kind' | 'proposal'>>, remember = ''): Reply {
  return {
    ...reply,
    parts: reply.parts.map((part) => (part.kind === 'proposal' ? { ...part, ...change } : part)),
    memory: remember ? `${reply.memory}\n${remember}`.trim() : reply.memory,
  }
}

/** The conversation once the user has moved on: a proposal left without an answer is no longer one. */
export function lapse(turns: Turn[]): Turn[] {
  const open = waiting(turns)
  if (!open) return turns
  const closed = settle(open.reply, { state: 'declined', note: 'Lasciata cadere: non ho toccato niente.' }, 'The user did not confirm: nothing was changed.')
  return turns.map((turn) => (turn.id === open.reply.id ? closed : turn))
}

/** What stops a proposal from being carried out as it is, in words; empty when nothing does. */
export function missing(proposed: Proposed): string {
  if (proposed.proposal.action === 'undo') return ''
  if (proposed.picked.length === 0) return 'Non è rimasta nessuna foto selezionata.'
  // the albums are named after their trips, and the trash has no folder
  if (proposed.proposal.action !== 'trash' && proposed.proposal.action !== 'albums' && !proposed.folder.trim()) {
    return 'Scrivi prima il nome della cartella nella scheda qui sopra.'
  }
  return ''
}

// What counts as a yes or a no to a proposal. Read here, from a fixed list: whether
// the user agreed to change their pictures is never left to a model to judge.
const YES = new Set([
  'sì', 'sì grazie', 'sì sì', 'sì dai', 'sì va bene', 'sì conferma', 'sì confermo', 'sì procedi', 'sì fallo', 'sì certo',
  'ok', 'okay', 'ok grazie', 'ok va bene', 'ok procedi', 'ok conferma', 'ok confermo', 'va bene', 'conferma', 'confermo',
  'procedi', 'fallo', 'fai pure', 'vai', 'certo', "d'accordo", 'yes',
])
const NO = new Set([
  'no', 'no grazie', 'no no', 'no annulla', 'no lascia stare', 'no non farlo', 'no fermo', 'no aspetta',
  'annulla', 'lascia stare', 'lascia perdere', 'non farlo', 'ferma', 'fermo', 'stop', 'niente',
])

/** Whether a message is a plain yes or a plain no. Anything else is neither: it is a new request. */
export function yesOrNo(text: string): 'yes' | 'no' | null {
  const plain = text
    .toLowerCase()
    .replace(/[’`]/g, "'")
    .replace(/[.,;:!?…]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    // dictated or typed in a hurry, the accent is often missing
    .replace(/\bsi\b/g, 'sì')
  if (YES.has(plain)) return 'yes'
  if (NO.has(plain)) return 'no'
  return null
}

/**
 * The pictures the user is looking at: the last ones that were shown, by a search
 * (the sure ones, if there are any) or in a proposal (the ones left ticked). They
 * are what "these" means in the next request.
 */
export function selection(turns: Turn[], gone: Pick<ReadonlySet<string>, 'has'> = new Set()): string[] {
  const shown = turns
    .flatMap((turn) => (turn.role === 'assistant' ? turn.parts : []))
    .findLast((part) => part.kind === 'photos' || (part.kind === 'proposal' && part.proposal.action !== 'undo'))
  let ids: string[] = []
  if (shown?.kind === 'photos') ids = (shown.sure.length > 0 ? shown.sure : shown.maybe).map((photo) => photo.id)
  if (shown?.kind === 'proposal') ids = shown.picked
  return ids.filter((id) => !gone.has(id))
}

const PURPOSE: Record<Job, string> = {
  tools: 'usa gli strumenti',
  chat: 'risponde a parole',
  vision: 'guarda le immagini',
}

/** What a model is for, in a few words. */
export function purposes(model: ModelInfo): string[] {
  return model.can.map((job) => PURPOSE[job])
}

/** Where a model runs on this computer, and what that means for whoever waits for it. */
export function placement(model: ModelInfo): { label: string; good: boolean } {
  switch (model.where) {
    case 'gpu':
      return { label: 'tutto sulla scheda video', good: true }
    case 'cpu':
      return { label: 'sul processore', good: true }
    case 'split':
      return { label: 'non sta nella scheda video: lento', good: false }
    case 'heavy':
      return { label: 'troppo grande per questo computer', good: false }
  }
}

/** The models that can do the talking, in the order the app prefers them. */
export function talkers(models: Models): ModelInfo[] {
  return models.order.chat.flatMap((name) => models.models.filter((model) => model.name === name))
}

/** "NVIDIA GeForce RTX 3050 Ti Laptop GPU" is too long for a side panel: keep the model. */
export function shortGpu(name: string): string {
  return name.replace(/^NVIDIA\s+/i, '').replace(/^GeForce\s+/i, '').replace(/\s+Laptop GPU$/i, '')
}
