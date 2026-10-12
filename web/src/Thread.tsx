import type { ReactNode } from 'react'
import type { Part, Reply, Turn } from './chat.ts'
import * as icons from './icons.tsx'
import { splitBlocks, splitInline } from './markdown.ts'
import PhotoResults from './Photos.tsx'
import ProposalCard from './Proposal.tsx'
import type { Answers } from './Proposal.tsx'

const IDEAS: { icon: ReactNode; title: string; text: string }[] = [
  { icon: <icons.Dog />, title: 'Trova le foto', text: 'Trovami le foto con un cane' },
  { icon: <icons.Folder />, title: 'Metti in ordine', text: 'Copia le foto delle chiese in una cartella Chiese' },
  { icon: <icons.Talk />, title: 'Chiedi qualcosa', text: "Spiegami in due righe cos'è una scheda video" },
]

/** The answers to the proposal of a reply, given the reply they are for. */
export type AnswersFor = (reply: Reply) => Answers

function Words({ text }: { text: string }) {
  return splitBlocks(text).map((block, index) =>
    block.kind === 'code' ? (
      <pre key={index}>
        <code>{block.text}</code>
      </pre>
    ) : (
      <p key={index}>
        {splitInline(block.text).map((piece, position) => {
          switch (piece.kind) {
            case 'code':
              return <code key={position}>{piece.text}</code>
            case 'bold':
              return <strong key={position}>{piece.text}</strong>
            case 'plain':
              return piece.text
          }
        })}
      </p>
    ),
  )
}

function PartView({ part, answers }: { part: Part; answers: Answers }) {
  switch (part.kind) {
    case 'text':
      return (
        <div className="words">
          <Words text={part.text} />
        </div>
      )
    case 'search':
      return (
        <p className="step">
          {part.place === 'phone' ? <icons.Phone /> : <icons.Search />}
          {part.place === 'phone' ? 'Cerco nelle foto del telefono:' : 'Cerco nelle foto:'} <q>{part.description}</q>
        </p>
      )
    case 'photos':
      return <PhotoResults found={part} />
    case 'proposal':
      return <ProposalCard proposed={part} answers={answers} />
  }
}

function ReplyView({ reply, answers }: { reply: Reply; answers: Answers }) {
  const busy = reply.status === 'waiting' || reply.status === 'writing'
  return (
    <article className="turn reply rise">
      <icons.Logo className="avatar" />
      <div className="body">
        {reply.parts.map((part, index) => (
          <PartView key={index} part={part} answers={answers} />
        ))}
        {reply.status === 'waiting' && (
          <p className="waiting">
            <span className="dots">
              <i />
              <i />
              <i />
            </span>
            {reply.loading ? 'Carico il modello in memoria…' : 'Ci penso…'}
          </p>
        )}
        {reply.status === 'error' && (
          <p className="notice" role="alert">
            Qualcosa non ha funzionato: {reply.error}
          </p>
        )}
        {reply.status === 'stopped' && <p className="meta">Fermato.</p>}
        {!busy && reply.model && (
          <p className="meta">
            {reply.model}
            {reply.seconds !== undefined && ` · ${reply.seconds.toLocaleString('it-IT')} s`}
          </p>
        )}
      </div>
    </article>
  )
}

/** The conversation, or, before it starts, what the app can be asked. */
export default function Thread({ turns, onIdea, answersFor }: { turns: Turn[]; onIdea: (text: string) => void; answersFor: AnswersFor }) {
  if (turns.length === 0) {
    return (
      <section className="welcome rise">
        <icons.Logo className="mark" />
        <h1>
          Dimmi cosa <span className="grad">ti serve.</span>
        </h1>
        <p className="lead">
          Cerco tra le tue foto e le metto in ordine, rispondo alle domande e scelgo io il modello giusto tra quelli che
          girano su questo computer. Niente esce da qui.
        </p>
        <ul className="ideas">
          {IDEAS.map((idea) => (
            <li key={idea.text}>
              <button type="button" onClick={() => onIdea(idea.text)}>
                <span className="idea-icon">{idea.icon}</span>
                <b>{idea.title}</b>
                <span>{idea.text}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    )
  }
  return (
    <>
      {turns.map((turn) =>
        turn.role === 'user' ? (
          <article key={turn.id} className="turn mine rise">
            <p>{turn.text}</p>
          </article>
        ) : (
          <ReplyView key={turn.id} reply={turn} answers={answersFor(turn)} />
        ),
      )}
    </>
  )
}
