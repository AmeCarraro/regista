import type { ReactNode } from 'react'
import type { Proposed } from './chat.ts'
import { missing } from './chat.ts'
import * as icons from './icons.tsx'
import { Thumb } from './Photos.tsx'

/** What the user can do with a proposal: leave pictures out, rename the folder, say yes or no, take it back afterwards. */
export type Answers = {
  onPick: (photo: string) => void
  onFolder: (name: string) => void
  onYes: () => void
  onNo: () => void
  onBack: () => void
}

function clock(when: string): string {
  const date = new Date(when)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

/** What a proposal is about, and what its yes button says. */
function wording(proposed: Proposed): { icon: ReactNode; title: string; hint: string; yes: string } {
  const { proposal } = proposed
  const count = proposed.picked.length
  switch (proposal.action) {
    case 'trash':
      return {
        icon: <icons.Trash />,
        title: 'Sposta nel cestino',
        hint: 'Niente viene cancellato davvero.',
        yes: count === 1 ? 'Sposta 1 foto nel cestino' : `Sposta ${count} foto nel cestino`,
      }
    case 'copy':
      return {
        icon: <icons.Folder />,
        title: 'Copia in una cartella',
        hint: 'Gli originali restano dove sono.',
        yes: count === 1 ? 'Copia 1 foto' : `Copia ${count} foto`,
      }
    case 'fetch':
      return {
        icon: <icons.Phone />,
        title: 'Copia dal telefono al computer',
        hint: 'Sul telefono restano dove sono.',
        yes: count === 1 ? 'Copia 1 foto dal telefono' : `Copia ${count} foto dal telefono`,
      }
    case 'undo': {
      const at = clock(proposal.when)
      const what =
        proposal.undoes === 'trash'
          ? `${proposal.count} foto spostate nel cestino`
          : proposal.undoes === 'receive'
            ? `${proposal.count} foto arrivate dal telefono in «${proposal.folder}»`
            : `${proposal.count} foto copiate in «${proposal.folder}»`
      return {
        icon: <icons.Undo />,
        title: "Annulla l'ultima modifica",
        hint: at ? `${what}, alle ${at}.` : `${what}.`,
        yes: proposal.undoes === 'trash' ? 'Rimettile a posto' : 'Togli le copie',
      }
    }
  }
}

/**
 * A change that waits for a yes: which pictures, where to, and the two answers.
 * Once answered it shrinks to a line that says how it went, with a way back.
 */
export default function ProposalCard({ proposed, answers }: { proposed: Proposed; answers: Answers }) {
  const { proposal, state } = proposed

  if (state === 'done') {
    return (
      <p className="outcome good">
        <icons.Check />
        <span>{proposed.note}</span>
        {proposed.entry && (
          <button type="button" className="link" onClick={answers.onBack}>
            Annulla
          </button>
        )}
      </p>
    )
  }
  if (state === 'undone' || state === 'declined') {
    return (
      <p className="outcome">
        {state === 'undone' ? <icons.Undo /> : <icons.Cross />}
        <span>{proposed.note}</span>
      </p>
    )
  }
  if (state === 'waiting') {
    // a phone has been asked: the pictures arrive when its app is open, which can be much later
    return (
      <p className="outcome" role="status">
        <span className="dots">
          <i />
          <i />
          <i />
        </span>
        <span>{proposed.note}</span>
      </p>
    )
  }

  const words = wording(proposed)
  const working = state === 'working'
  const picked = new Set(proposed.picked)
  return (
    <section className="proposal" aria-label={words.title}>
      <header>
        <span className="badge">{words.icon}</span>
        <div>
          <b>{words.title}</b>
          <span>{words.hint}</span>
        </div>
      </header>

      {(proposal.action === 'copy' || proposal.action === 'fetch') && (
        <label className="folder-name">
          <icons.Folder />
          <span>Cartella</span>
          <input
            value={proposed.folder}
            placeholder="Come la chiamo?"
            maxLength={60}
            disabled={working}
            onChange={(event) => answers.onFolder(event.target.value)}
          />
        </label>
      )}

      {proposal.action !== 'undo' && (
        <ul className="picks">
          {proposal.photos.map((photo) => (
            <li key={photo.id}>
              <label className={picked.has(photo.id) ? 'pick' : 'pick off'} title={photo.name}>
                <input
                  type="checkbox"
                  checked={picked.has(photo.id)}
                  disabled={working}
                  aria-label={photo.name}
                  onChange={() => answers.onPick(photo.id)}
                />
                <Thumb id={photo.id} />
                <span className="tick">
                  <icons.Check />
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      {proposed.problem && (
        <p className="notice" role="alert">
          {proposed.problem}
        </p>
      )}

      <footer>
        <button type="button" className="go" disabled={working || missing(proposed) !== ''} onClick={answers.onYes}>
          {working ? 'Un attimo…' : words.yes}
        </button>
        <button type="button" className="quiet-button" disabled={working} onClick={answers.onNo}>
          Lascia stare
        </button>
        {proposal.action !== 'undo' && proposal.photos.length > 1 && <span className="fine">Tocca una foto per lasciarla fuori.</span>}
      </footer>
    </section>
  )
}
