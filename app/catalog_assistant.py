"""Text-only direction and saved-data photo search; file actions remain proposals."""
import asyncio
import time

import llm
import orchestrator
from photo_annotator import MODEL
from photo_search import natural_plan, search


async def reply(history, models, library, actions, selection, phones=None):
    started = time.perf_counter()
    asked = next((message['content'] for message in reversed(history) if message['role'] == 'user'), '')
    if orchestrator.TWINS.search(asked):
        with library.catalog.connect() as db:
            groups = db.execute('SELECT count(*) n FROM file_locations WHERE present=1 GROUP BY asset_id HAVING count(*)>1').fetchall()
        message = f"{len(groups)} contenuti con copie identiche (SHA-256), {sum(row['n'] - 1 for row in groups)} copie aggiuntive. Le foto sono mostrate una volta per contenuto nel Catalogo."
        yield {'type': 'text', 'text': message}
        yield {'type': 'done', 'model': '', 'seconds': 0, 'memory': message}
        return
    if orchestrator.ALBUMS.search(asked) or orchestrator.BY_KIND.search(asked):
        events = orchestrator._albums(asked, library, actions, None) if orchestrator.ALBUMS.search(asked) else orchestrator._by_kind(library)
        async for event in events:
            yield event
        return
    exact = next((model for model in models if model['name'] == MODEL), None)
    if exact is None:
        message = f'Il modello configurato {MODEL} non è installato. La ricerca con i filtri del Catalogo resta disponibile.'
        yield {'type': 'text', 'text': message}
        yield {'type': 'done', 'model': '', 'seconds': 0, 'memory': message}
        return
    yield {'type': 'start', 'director': MODEL, 'writer': MODEL, 'loading': not exact['loaded']}
    decision = await orchestrator.decide(MODEL, history)
    action = decision['action']
    memory = ''
    if action in ('find_photos', 'count_photos') or (action == 'answer' and orchestrator.FIND.search(asked) and not orchestrator.HOW.search(asked)):
        plan = await natural_plan(asked)
        found = await asyncio.to_thread(search, library.catalog, plan)
        coverage = found['coverage']
        result = {'sure': [{**photo, 'score': 1.0} for photo in found['photos']], 'maybe': [], 'matching': found['total'],
                  'indexed': coverage['discovered'], 'partial': coverage['coverage'] < 100}
        yield {'type': 'step', 'tool': 'find_photos', 'arguments': {'description': asked, 'place': 'computer'}}
        if action != 'count_photos':
            yield {'type': 'photos', 'description': asked, 'place': 'computer', **result}
        memory = f"Ho trovato {found['total']} foto nei dati salvati. Catalogo analizzato al {coverage['coverage']}%."
        yield {'type': 'text', 'text': memory}
    elif action in orchestrator.CHANGES:
        # Existing confirmation cards and journal/undo remain the only way to mutate files.
        selected = list(selection)
        if decision['caption'] and action != 'undo':
            plan = await natural_plan(asked)
            found = await asyncio.to_thread(search, library.catalog, plan)
            selected = [photo['id'] for photo in found['photos']]
            decision = {**decision, 'caption': ''}
        if action != 'undo' and any(library.relative_of(identifier) is None for identifier in selected):
            message = 'Questa selezione contiene foto di una radice aggiuntiva. Le azioni con annulla sono disponibili nella cartella principale; scegli foto di quella cartella.'
            yield {'type': 'text', 'text': message}
            yield {'type': 'done', 'model': MODEL, 'seconds': 0, 'memory': message}
            return
        plan = await asyncio.to_thread(orchestrator.propose, decision, library, actions, selected)
        yield {'type': 'text', 'text': plan['text']}
        if plan['proposal']:
            yield {'type': 'proposal', **plan['proposal']}
        memory = plan['memory']
    else:
        async for kind, value in llm.stream(MODEL, orchestrator._conversation(history, orchestrator.TALK)):
            if kind == 'text':
                memory += value
                yield {'type': 'text', 'text': value}
    yield {'type': 'done', 'model': MODEL, 'seconds': round(time.perf_counter() - started, 1), 'memory': memory}
