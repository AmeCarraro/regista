import { useEffect, useMemo, useRef, useState } from 'react'
import { carryOut, chatStream, fetchChanges, fetchLibrary, fetchModels, fetchPhone, fetchTransfer, makeAlbums, readFolderAgain, takeBack, testModels } from './api.ts'
import type { Changes, Library, Models, Outcome, PhoneState } from './api.ts'
import { apply, lapse, missing, newReply, selection, settle, tail, toMessages, waiting, yesOrNo } from './chat.ts'
import type { Proposed, Reply, Turn } from './chat.ts'
import Composer from './Composer.tsx'
import * as icons from './icons.tsx'
import Music from './Music.tsx'
import type { Answers } from './Proposal.tsx'
import { Shelf } from './shelf.ts'
import type { Gone } from './shelf.ts'
import Side from './Side.tsx'
import Thread from './Thread.tsx'

const LEFT_ALONE = 'Va bene, non tocco niente.'

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') ?? 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])
  return [theme, () => setTheme(theme === 'dark' ? 'light' : 'dark')]
}

export default function App() {
  const [theme, toggleTheme] = useTheme()
  const [turns, setTurns] = useState<Turn[]>([])
  const [model, setModel] = useState('auto')
  const [models, setModels] = useState<Models | null>(null)
  const [library, setLibrary] = useState<Library | null>(null)
  const [changes, setChanges] = useState<Changes | null>(null)
  const [phone, setPhone] = useState<PhoneState | null>(null)
  // the pictures that went to the trash since they were shown in this conversation
  const [gone, setGone] = useState<ReadonlyMap<string, Gone>>(new Map())
  const [testing, setTesting] = useState<{ model: string; done: number; of: number } | null>(null)
  const [panel, setPanel] = useState(false)
  // the music in place of the chat: the chat stays as it was, and the music goes on when it is shown again
  const [listening, setListening] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const nextId = useRef(1)
  const end = useRef<HTMLDivElement>(null)
  const askLibrary = useRef(() => {})
  const last = turns.at(-1)
  const busy = last?.role === 'assistant' && (last.status === 'waiting' || last.status === 'writing')

  function loadModels() {
    fetchModels().then(setModels, () => setModels(null))
  }

  function loadChanges() {
    fetchChanges().then(setChanges, () => setChanges(null))
  }

  function loadPhone() {
    fetchPhone().then(setPhone, () => setPhone(null))
  }

  useEffect(() => {
    loadModels()
    loadChanges()
  }, [])

  // Which phones are connected is shown, and decided, only at the computer: inside a phone's app the page does not ask.
  const atComputer = library?.door === 'computer'
  useEffect(() => {
    if (!atComputer) return
    loadPhone()
    // a phone connects, sends its pictures and answers requests on its own time: look again every few seconds
    const timer = setInterval(loadPhone, 5000)
    return () => clearInterval(timer)
  }, [atComputer])

  // the requests to a phone that are still open, each with the reply whose card follows it
  const awaited = turns.flatMap((turn) =>
    turn.role === 'assistant'
      ? turn.parts.flatMap((part) => (part.kind === 'proposal' && part.state === 'waiting' && part.transfer ? [{ reply: turn.id, transfer: part.transfer }] : []))
      : [],
  )
  const awaitedKey = awaited.map((one) => `${one.reply}:${one.transfer}`).join(',')
  useEffect(() => {
    if (!awaitedKey) return
    const timer = setInterval(() => {
      for (const one of awaited) {
        fetchTransfer(one.transfer).then(
          (now) => {
            if (now.state === 'done') {
              patch(one.reply, (current) => settle(current, { state: 'done', note: now.text, entry: now.entry, transfer: '' }, now.memory))
              // pictures that left the phone are no longer there to be shown or chosen
              if (now.gone.length > 0) setGone((before) => new Map([...before, ...now.gone.map((id): [string, Gone] => [id, 'trash'])]))
              loadChanges()
              loadPhone()
            } else {
              patch(one.reply, (current) => settle(current, { note: now.text }))
            }
          },
          // the service may be restarting: the next look will tell
          () => {},
        )
      }
    }, 1500)
    return () => clearInterval(timer)
    // the list is rebuilt at every render: its key says when it really changed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [awaitedKey])

  // the number of pictures is asked again every second while they are being read, and rarely otherwise
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    function ask() {
      clearTimeout(timer)
      fetchLibrary()
        .then(
          (value) => {
            if (alive) setLibrary(value)
            return value.running
          },
          () => {
            if (alive) setLibrary(null)
            return false
          },
        )
        .then((reading) => {
          if (alive) timer = setTimeout(ask, reading ? 1000 : 30000)
        })
    }
    askLibrary.current = ask
    ask()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [])

  // follow the conversation as it grows, but stay put when a picture is ticked in a card further up
  const grown = tail(turns)
  useEffect(() => {
    // not before the first request: on a small screen it would hide the top of the welcome
    if (grown !== '0') end.current?.scrollIntoView({ block: 'end' })
  }, [grown])

  function patch(id: number, change: (reply: Reply) => Reply) {
    setTurns((all) => all.map((turn) => (turn.id === id && turn.role === 'assistant' ? change(turn) : turn)))
  }

  /** After the pictures changed on disk: what the panel shows, and which pictures are no longer there. */
  function afterChange(outcome: Outcome) {
    if (outcome.kind !== 'copy' && outcome.ids.length > 0) {
      setGone((before) => {
        const after = new Map(before)
        for (const id of outcome.ids) {
          if (outcome.kind === 'trash' || outcome.kind === 'move') after.set(id, outcome.kind)
          else after.delete(id)
        }
        return after
      })
    }
    loadChanges()
    askLibrary.current()
  }

  /** Carries out the proposal of a reply, now that the user said yes. Returns how it went, in words. */
  async function carry(reply: Reply, proposed: Proposed): Promise<string> {
    const stops = missing(proposed)
    if (stops) return stops
    patch(reply.id, (current) => settle(current, { state: 'working', problem: '' }))
    try {
      const { proposal } = proposed
      const outcome =
        proposal.action === 'undo'
          ? await takeBack(proposal.of)
          : proposal.action === 'albums'
            ? // each album with the pictures still ticked; an album left with none is not made
              await makeAlbums(
                proposal.albums
                  .map((album) => ({ folder: album.folder, ids: album.ids.filter((id) => proposed.picked.includes(id)) }))
                  .filter((album) => album.ids.length > 0),
              )
            : await carryOut(proposal.action, proposed.picked, proposed.folder)
      if (outcome.transfer) {
        // a phone was asked: the card now follows the request until the pictures have arrived
        const transfer = outcome.transfer
        patch(reply.id, (current) => settle(current, { state: 'waiting', note: outcome.text, folder: outcome.folder, transfer }, outcome.memory))
        loadPhone()
        return outcome.text
      }
      patch(reply.id, (current) => settle(current, { state: 'done', note: outcome.text, entry: outcome.id, folder: outcome.folder }, outcome.memory))
      if (proposal.action === 'undo') {
        // the card of the change that was just taken back must not offer to take it back again
        setTurns((all) =>
          all.map((turn) =>
            turn.role === 'assistant' && turn.parts.some((part) => part.kind === 'proposal' && part.state === 'done' && part.entry === proposal.of)
              ? settle(turn, { state: 'undone', note: outcome.text })
              : turn,
          ),
        )
      }
      afterChange(outcome)
      return outcome.text
    } catch (error) {
      const problem = error instanceof Error ? error.message : String(error)
      // it still waits: the user can try again, or leave it
      patch(reply.id, (current) => settle(current, { state: 'asked', problem }))
      return `Non ci sono riuscito: ${problem}`
    }
  }

  function decline(reply: Reply): string {
    patch(reply.id, (current) => settle(current, { state: 'declined', note: 'Lasciato stare: non ho toccato niente.' }, 'The user declined: nothing was changed.'))
    return LEFT_ALONE
  }

  /** Takes back a change that was carried out from the card of a reply. */
  async function back(reply: Reply, proposed: Proposed) {
    patch(reply.id, (current) => settle(current, { state: 'working', problem: '' }))
    try {
      const outcome = await takeBack(proposed.entry)
      patch(reply.id, (current) => settle(current, { state: 'undone', note: outcome.text }, outcome.memory))
      afterChange(outcome)
    } catch (error) {
      const problem = error instanceof Error ? error.message : String(error)
      patch(reply.id, (current) => settle(current, { state: 'done', note: `${proposed.note} Non sono riuscito ad annullare: ${problem}` }))
    }
  }

  /** What the buttons of the proposal of a reply do. */
  function answersFor(reply: Reply): Answers {
    const proposed = reply.parts.find((part) => part.kind === 'proposal')
    if (proposed?.kind !== 'proposal') return { onPick() {}, onPickMany() {}, onFolder() {}, onYes() {}, onNo() {}, onBack() {} }
    return {
      onPick: (photo) =>
        patch(reply.id, (current) =>
          settle(current, { picked: proposed.picked.includes(photo) ? proposed.picked.filter((id) => id !== photo) : [...proposed.picked, photo] }),
        ),
      onPickMany: (photos, on) =>
        patch(reply.id, (current) => {
          // from what is ticked now: an album is many pictures, changed in one go
          const part = current.parts.find((one) => one.kind === 'proposal')
          const before = part?.kind === 'proposal' ? part.picked : []
          return settle(current, { picked: on ? [...new Set([...before, ...photos])] : before.filter((id) => !photos.includes(id)) })
        }),
      onFolder: (name) => patch(reply.id, (current) => settle(current, { folder: name })),
      onYes: () => void carry(reply, proposed),
      onNo: () => void decline(reply),
      onBack: () => void back(reply, proposed),
    }
  }

  /** An answer of the app's own, written without asking a model. */
  function say(text: string, words: Promise<string> | string) {
    const question: Turn = { id: nextId.current++, role: 'user', text }
    const reply = newReply(nextId.current++)
    setTurns((all) => [...all, question, reply])
    void Promise.resolve(words).then((said) =>
      patch(reply.id, (current) => ({ ...current, status: 'done', parts: [{ kind: 'text', text: said }], memory: said })),
    )
  }

  async function send(text: string) {
    setPanel(false)
    // a plain yes or no to a proposal is read here, and never by a model
    const open = waiting(turns)
    const answer = open ? yesOrNo(text) : null
    if (open && answer) {
      say(text, answer === 'yes' ? carry(open.reply, open.proposed) : decline(open.reply))
      return
    }

    const abort = new AbortController()
    controller.current = abort
    const question: Turn = { id: nextId.current++, role: 'user', text }
    const reply = newReply(nextId.current++)
    // anything else moves the conversation on: a proposal left without an answer lapses
    const conversation = [...lapse(turns), question]
    setTurns([...conversation, reply])

    let finished = false
    try {
      for await (const event of chatStream(toMessages(conversation), model, selection(turns, gone), abort.signal)) {
        if (event.type === 'done' || event.type === 'error') finished = true
        patch(reply.id, (current) => apply(current, event))
      }
      if (!finished) {
        patch(reply.id, (current) => ({ ...current, status: 'error', error: 'la connessione si è chiusa prima della fine.' }))
      }
    } catch (error) {
      // aborting the request is how Stop works, so that is not a failure
      const message = error instanceof Error ? error.message : String(error)
      patch(reply.id, (current) =>
        abort.signal.aborted ? { ...current, status: 'stopped' } : { ...current, status: 'error', error: message },
      )
    }
    // which model is in memory may have changed
    loadModels()
  }

  async function test() {
    const abort = new AbortController()
    try {
      for await (const event of testModels(abort.signal)) {
        if (event.type === 'progress') setTesting({ model: event.model, done: event.case - 1, of: event.cases })
      }
    } finally {
      setTesting(null)
      loadModels()
    }
  }

  function readAgain() {
    void readFolderAgain().then(() => askLibrary.current())
  }

  // changes whenever the library does: a small copy that could not be loaded is then asked for again
  const shelf = useMemo(() => ({ gone, epoch: `${library?.indexed ?? 0}:${library?.running ? 1 : 0}` }), [gone, library?.indexed, library?.running])

  return (
    <div className="app">
      <div className="backdrop">
        <i />
        <i />
        <i />
      </div>

      <aside className={panel ? 'side open' : 'side'}>
        <Side
          models={models}
          library={library}
          changes={changes}
          phone={phone}
          onPhoneChange={loadPhone}
          testing={testing}
          onTest={() => void test()}
          onReadAgain={readAgain}
          theme={theme}
          onTheme={toggleTheme}
          listening={listening}
          onListen={(chosen) => {
            setListening(chosen)
            setPanel(false)
          }}
        />
      </aside>
      {panel && <button type="button" className="scrim" aria-label="Chiudi il pannello" onClick={() => setPanel(false)} />}

      <main className={listening ? 'chat listening' : 'chat'}>
        <header className="top">
          <button type="button" className="round ghost small" aria-label="Apri il pannello" onClick={() => setPanel(true)}>
            <icons.Menu />
          </button>
          <icons.Logo />
          <b>Regista</b>
        </header>
        <div className="thread">
          <Shelf value={shelf}>
            <Thread turns={turns} onIdea={(text) => void send(text)} answersFor={answersFor} />
          </Shelf>
          <div ref={end} />
        </div>
        <Music visible={listening} />
        <Composer
          models={models}
          model={model}
          onModel={setModel}
          busy={busy}
          onSend={(text) => void send(text)}
          onStop={() => controller.current?.abort()}
        />
      </main>
    </div>
  )
}
