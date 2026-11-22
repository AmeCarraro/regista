import { useEffect, useState } from 'react'
import { catalogRequest } from './catalogApi.ts'
import type { DocumentFile } from './api.ts'
import './documents.css'

declare global { interface Window { RegistaPc?: { openDocument(id:string,download:boolean):void } } }

export function DocumentFiles({ files, total }: { files: DocumentFile[]; total: number }) {
  return <div className="document-results" aria-label="Documenti trovati">
    {total>1 && <p className="document-note">{total} corrispondenze: scegli il documento da aprire o scaricare.</p>}
    {files.filter(file => /^[a-f0-9]{64}$/.test(file.id)).map(file => <article className="document-card" key={file.id}>
      <div className="document-type">{file.extension.slice(1).toUpperCase()}</div><div className="document-info"><b>{file.name}</b>
        <p>{file.day || 'Data non disponibile'} · {(file.size/1024).toFixed(1)} KB</p>
        <p>{file.tags.join(' · ')}</p>
        {file.text_state!=='ready' && <p className="document-note">{file.reason || 'Testo in attesa di indicizzazione'}</p>}
        <div className="document-actions"><a href={`/api/documents/${file.id}/file`} target="_blank" rel="noopener" onClick={event=> { if(window.RegistaPc) { event.preventDefault(); window.RegistaPc.openDocument(file.id,false) } }}>Apri originale</a><a href={`/api/documents/${file.id}/file?download=true`} download={file.name} onClick={event=> { if(window.RegistaPc) { event.preventDefault(); window.RegistaPc.openDocument(file.id,true) } }}>Scarica</a></div>
        <details><summary>Provenienza</summary>{file.origins?.map((origin,index) => <p key={index}>{origin.folder}/{origin.name}</p>)}</details>
      </div>
    </article>)}
    {files.length<total && <p className="document-note">Mostrati {files.length} risultati. Restringi la ricerca o usa la sezione Documenti.</p>}
  </div>
}

export default function Documents({ visible }: { visible: boolean }) {
  const [query,setQuery]=useState('')
  const [kind,setKind]=useState('')
  const [source,setSource]=useState('')
  const [since,setSince]=useState('')
  const [until,setUntil]=useState('')
  const [tag,setTag]=useState('')
  const [offset,setOffset]=useState(0)
  const [result,setResult]=useState<{ files:DocumentFile[]; total:number } | null>(null)
  const [problem,setProblem]=useState('')
  useEffect(() => {
    if(!visible) return
    let active=true
    const timer=setTimeout(() => void catalogRequest<{ files:DocumentFile[]; total:number }>('/api/documents/search',{ query,kind,source,since,until,tag,offset }).then(
      value=> { if(active) { setResult(value); setProblem('') } },error=> { if(active) setProblem(String(error.message)) }),200)
    return()=> { active=false; clearTimeout(timer) }
  },[visible,query,kind,source,since,until,tag,offset])
  if(!visible) return null
  return <section className="catalog-page documents-page" aria-label="Documenti"><header className="catalog-header"><div><h1>Documenti</h1><p>Originali, provenienza e testo estraibile, sul tuo PC.</p></div></header>
    <div className="catalog-search"><label>Cerca per nome o contenuto<input value={query} onChange={e=> { setQuery(e.target.value); setOffset(0) }} placeholder="Bolletta ottobre, spese…" maxLength={1000} /></label>
      <div className="catalog-filters"><label>Tipo<select value={kind} onChange={e=> { setKind(e.target.value); setOffset(0) }}><option value="">Tutti</option>{['pdf','excel','word','csv','txt'].map(value=><option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label>
        <label>Provenienza<select value={source} onChange={e=> { setSource(e.target.value); setOffset(0) }}><option value="">Tutte</option><option value="normal">Altre cartelle</option><option value="whatsapp">WhatsApp</option><option value="telegram">Telegram</option></select></label>
        <label>Dal<input type="date" value={since} onChange={e=> { setSince(e.target.value); setOffset(0) }} /></label><label>Al<input type="date" value={until} onChange={e=> { setUntil(e.target.value); setOffset(0) }} /></label>
        <label>Tag<input value={tag} onChange={e=> { setTag(e.target.value); setOffset(0) }} /></label>
      </div>
    </div>
    <p className="catalog-muted">Importa i documenti da «Impostazioni e backup» sul telefono. Puoi richiedere la selezione anche dalla sezione Telefono del PC. La ricerca non richiede Qwen in memoria.</p>
    {problem && <p role="alert">{problem}</p>}
    {result && <><p role="status">{result.total} documenti</p><DocumentFiles files={result.files} total={result.total} />
      <div className="catalog-toolbar"><button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-40))}>Precedenti</button><button disabled={offset+40>=result.total} onClick={()=>setOffset(offset+40)}>Successive</button></div></>}
  </section>
}
