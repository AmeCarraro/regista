import { useState } from 'react'
import type { Changes, Library, ModelInfo, Models, PhoneState, Suggested } from './api.ts'
import { placement, purposes, shortGpu } from './chat.ts'
import * as icons from './icons.tsx'
import PhoneCard from './Phone.tsx'

const WHERE: Record<Suggested['where'], string> = {
  gpu: 'sta tutto nella scheda video, quindi è veloce',
  cpu: 'gira sul processore, più piano',
  split: 'la scheda video è piccola: una parte girerà sul processore, più piano',
}

/** The model this computer should have for the job of director, and how to get it when it is not there. */
function Advice({ suggested }: { suggested: Suggested }) {
  const [copied, setCopied] = useState(false)

  function copy() {
    // the clipboard exists only where the page is served safely: elsewhere the command is still there to read
    void navigator.clipboard?.writeText(suggested.command).then(
      () => setCopied(true),
      () => setCopied(false),
    )
  }

  if (suggested.installed) {
    return (
      <p className="advice">
        <icons.Check />
        <span>
          Tra i modelli che conosco, il più adatto a questo computer è <b className="mono">{suggested.name}</b>: ce l'hai già.
        </span>
      </p>
    )
  }
  return (
    <div className="advice wanted">
      <p>
        <icons.Spark />
        <span>
          Per questo computer ti consiglio <b className="mono">{suggested.name}</b> ({suggested.gigabytes.toLocaleString('it-IT')} GB):{' '}
          {WHERE[suggested.where]}.
        </span>
      </p>
      <p className="fine">Per scaricarlo apri un terminale e scrivi:</p>
      <button type="button" className="command mono" onClick={copy} title="Copia il comando">
        {suggested.command}
        <span>{copied ? 'copiato' : 'copia'}</span>
      </button>
      <p className="fine">Poi premi «Prova i modelli» qui sotto: è la prova a decidere chi fa il regista.</p>
    </div>
  )
}

type Props = {
  models: Models | null
  library: Library | null
  /** What can be changed in the picture folder, and how much is in the trash. */
  changes: Changes | null
  /** The phones that were let in, and whether more can be. */
  phone: PhoneState | null
  /** Called when a phone was let in or shut out, to look at the phones again. */
  onPhoneChange: () => void
  /** While the models are being tried: which one, and how far. */
  testing: { model: string; done: number; of: number } | null
  onTest: () => void
  onReadAgain: () => void
  theme: string
  onTheme: () => void
  /** Whether the music is shown in place of the chat. */
  listening: boolean
  onListen: (listening: boolean) => void
}

function ModelRow({ model, director }: { model: ModelInfo; director: boolean }) {
  const place = placement(model)
  return (
    <li className={model.can.length ? 'model' : 'model quiet'}>
      <p className="model-name">
        <span className={model.loaded ? 'dot live' : 'dot'} title={model.loaded ? 'In memoria adesso' : 'Non in memoria'} />
        <b className="mono">{model.name}</b>
        <span className="size mono">{model.gigabytes.toLocaleString('it-IT')} GB</span>
      </p>
      <p className="tags">
        {director && <span className="tag director">regista</span>}
        {purposes(model).map((purpose) => (
          <span key={purpose} className="tag">
            {purpose}
          </span>
        ))}
        {model.can.length === 0 && <span className="tag">solo per la ricerca nei testi</span>}
      </p>
      {model.can.length > 0 && (
        <p className={place.good ? 'fine' : 'fine warn'}>
          {place.label}
          {model.tested && ` · provato: ${model.tested.right} giuste su ${model.tested.cases}, ${Math.round(model.tested.tokens_per_second)} token/s`}
        </p>
      )}
    </li>
  )
}

/** The side panel: the computer, the models on it with what each is for, and the pictures. */
export default function Side({ models, library, changes, phone, onPhoneChange, testing, onTest, onReadAgain, theme, onTheme, listening, onListen }: Props) {
  const machine = models?.hardware
  const director = models?.order.tools[0]
  const reading = library?.running

  return (
    <>
      <header className="brand">
        <icons.Logo />
        <div>
          <b>Regista</b>
          <span>il tuo assistente, in locale</span>
        </div>
        <button type="button" className="round ghost small" aria-label="Cambia tra scuro e chiaro" onClick={onTheme}>
          {theme === 'dark' ? <icons.Sun /> : <icons.Moon />}
        </button>
      </header>

      <nav className="views" aria-label="Cosa mostrare">
        <button type="button" aria-pressed={!listening} onClick={() => onListen(false)}>
          <icons.Talk /> Chat
        </button>
        <button type="button" aria-pressed={listening} onClick={() => onListen(true)}>
          <icons.Note /> Musica
        </button>
      </nav>

      <section className="panel">
        <h2>
          <icons.Chip /> Questo computer
        </h2>
        {machine && (machine.gpu || machine.ram_gb > 0) ? (
          <ul className="facts">
            <li>
              <span>Scheda video</span>
              <b>{machine.gpu ? `${shortGpu(machine.gpu)} · ${(machine.gpu_gb || machine.unproven_gb).toLocaleString('it-IT')} GB` : 'nessuna: si usa il processore'}</b>
            </li>
            {machine.unproven_gb > 0 && (
              <li className="note">Non so ancora se i modelli usano questa scheda: per ora conto sul processore. Lo scopro con «Prova i modelli».</li>
            )}
            <li>
              <span>Memoria</span>
              <b>{Math.round(machine.ram_gb)} GB</b>
            </li>
            <li>
              <span>Processore</span>
              <b>{machine.cores} core</b>
            </li>
          </ul>
        ) : (
          <p className="fine">Non so com'è fatto questo computer: avvia l'app con run.ps1.</p>
        )}
      </section>

      <section className="panel">
        <h2>
          <icons.Layers /> Modelli locali
        </h2>
        {models?.problem && <p className="fine warn">Non raggiungo Ollama: è acceso? ({models.problem})</p>}
        {models && !models.problem && models.models.length === 0 && <p className="fine">Nessun modello installato in Ollama.</p>}
        <ul className="models">
          {models?.models.map((model) => (
            <ModelRow key={model.name} model={model} director={model.name === director} />
          ))}
        </ul>
        {models?.suggested && !models.problem && <Advice suggested={models.suggested} />}
        {testing ? (
          <p className="fine progress">
            Provo <b className="mono">{testing.model}</b>: {testing.done} di {testing.of}
            <span className="bar">
              <i style={{ width: `${(testing.done / testing.of) * 100}%` }} />
            </span>
          </p>
        ) : (
          <button type="button" className="quiet-button" onClick={onTest} disabled={!models || models.models.length === 0}>
            <icons.Bolt /> Prova i modelli su questo computer
          </button>
        )}
        <p className="fine">
          Il "regista" legge ogni richiesta e decide cosa fare. Viene scelto tra i modelli che stanno in questo computer,
          preferendo chi, alla prova, usa meglio gli strumenti.
        </p>
      </section>

      <section className="panel">
        <h2>
          <icons.Picture /> Le tue foto
        </h2>
        {library ? (
          <>
            <p className="count">
              <b className="grad mono">{library.indexed.toLocaleString('it-IT')}</b>
              <span>{reading ? `lette, su ${library.total.toLocaleString('it-IT')}` : 'foto che conosco'}</span>
            </p>
            {reading && (
              <span className="bar">
                <i style={{ width: `${library.total ? (library.done / library.total) * 100 : 0}%` }} />
              </span>
            )}
            {library.error && <p className="fine warn">La lettura si è fermata: {library.error}</p>}
            <p className="fine folder mono" title={library.folder}>
              {library.folder}
            </p>
            <button type="button" className="quiet-button" onClick={onReadAgain} disabled={reading}>
              <icons.Refresh /> Rileggi la cartella
            </button>
            {changes && !changes.writable ? (
              <p className="fine">Cartella in sola lettura: posso cercare, ma non spostare né copiare.</p>
            ) : (
              <>
                {changes && changes.trash > 0 && (
                  <p className="trash">
                    <icons.Trash />
                    <b className="mono">{changes.trash.toLocaleString('it-IT')}</b> nel cestino
                    <span className="mono">.regista\cestino</span>
                  </p>
                )}
                <p className="fine">
                  Non cancello mai niente. Quello che elimini va nel cestino, dentro la cartella delle foto, e torna al suo
                  posto con «annulla»; le copie vanno nella sottocartella Raccolte. Ogni modifica parte solo dopo il tuo sì.
                </p>
              </>
            )}
          </>
        ) : (
          <p className="fine">Non raggiungo il servizio.</p>
        )}
      </section>

      {library?.door !== 'phone' && <PhoneCard phone={phone} onChange={onPhoneChange} />}
    </>
  )
}
