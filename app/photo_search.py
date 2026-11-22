"""Validated search plans compiled into parameterized SQLite/FTS queries."""
from datetime import date
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import llm
from photo_annotator import COUNT_FORMS, COUNTS, MODEL
from photo_catalog import CLASSIFICATION_SQL, normalized

SYNONYMS = [('cane', 'cani', 'cucciolo', 'cuccioli', 'dog', 'dogs'),
            ('gatto', 'gatti', 'cat', 'cats'), ('nero', 'nera', 'neri', 'nere', 'black'),
            ('tv', 'televisore', 'televisori', 'televisione', 'television', 'televisions'),
            ('mare', 'sea'), ('neve', 'snow'), ('tramonto', 'tramonti', 'sunset'), ('lago', 'lake')]


class SearchPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    terms: list[str] = Field(default_factory=list, max_length=30)
    operator: Literal['and', 'or'] = 'and'
    exclude: list[str] = Field(default_factory=list, max_length=30)
    since: str = ''
    until: str = ''
    place: str = Field(default='', max_length=100)
    folder: str = Field(default='', max_length=300)
    root_id: str = Field(default='', max_length=64)
    tag: str = Field(default='', max_length=100)
    order: Literal['newest', 'oldest', 'name'] = 'newest'
    limit: int = Field(default=60, ge=1, le=120)
    offset: int = Field(default=0, ge=0, le=1000000)
    stage: Literal['all', 'classified', 'to_catalog', 'needs_review'] = 'all'
    kind: Literal['all','image','video'] = 'all'
    album: str = Field(default='',max_length=64)
    include_hidden: bool = False

    @field_validator('terms', 'exclude')
    @classmethod
    def terms_bounded(cls, values):
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError('Termine di ricerca non valido.')
        return [normalized(value) for value in values]

    @field_validator('terms')
    @classmethod
    def quantities_belong_to_the_next_subject(cls, values):
        terms, index = [], 0
        while index < len(values):
            if values[index] in COUNT_FORMS and index + 1 < len(values) and values[index + 1] not in COUNT_FORMS:
                terms.append(values[index] + ' ' + values[index + 1])
                index += 2
            else:
                terms.append(values[index])
                index += 1
        return terms

    @field_validator('since', 'until')
    @classmethod
    def dates_valid(cls, value):
        if value:
            date.fromisoformat(value)
        return value


def variants(term: str) -> list[str]:
    first, space, rest = term.partition(' ')
    if first in COUNT_FORMS:
        count = COUNT_FORMS[first]
        return [prefix + space + rest for prefix in (str(count), COUNTS[count])]
    return next((list(group) for group in SYNONYMS if term in group), [term])


def expression(term: str) -> str:
    return '(' + ' OR '.join('"' + word.replace('"', '""') + '"' for word in variants(term)) + ')'


async def natural_plan(query: str) -> SearchPlan:
    response = await llm.structured(MODEL, [
        {'role': 'system', 'content': 'Traduci una ricerca fotografica in JSON, senza SQL o azioni su file. '
         'Termini di contenuto in italiano. Separa AND, OR e negazioni. Date ISO complete solo come estremi del periodo '
         '(marzo 2025: 2025-03-01 / 2025-03-31). place indica solo un luogo geografico richiesto, folder un indizio nel percorso. '
         'Non inventare termini assenti. root_id vuoto; offset 0. Oggi: ' + date.today().isoformat()},
        {'role': 'user', 'content': query}], SearchPlan.model_json_schema(), max_tokens=700)
    if not response.get('done') or response.get('done_reason') == 'length':
        raise ValueError('Piano di ricerca incompleto: usa i filtri.')
    plan = SearchPlan.model_validate_json(response.get('message', {}).get('content', ''))
    if plan.since and plan.until and plan.since > plan.until:
        raise ValueError('Periodo non valido.')
    return plan


def search(catalog, plan: SearchPlan) -> dict:
    where, values = ['l.present=1'], []
    if plan.kind!='all':
        where.append("coalesce(json_extract(l.metadata,'$.media_kind'),'image')=?")
        values.append(plan.kind)
    if plan.album:
        where.append('EXISTS(SELECT 1 FROM collection_items ci WHERE ci.asset_id=a.id AND ci.collection_id=?)')
        values.append(plan.album)
    elif not plan.include_hidden:
        where.append('NOT EXISTS(SELECT 1 FROM hidden_media h WHERE h.asset_id=a.id)')
        where.append('NOT EXISTS(SELECT 1 FROM collection_items ci JOIN collections c ON c.id=ci.collection_id WHERE ci.asset_id=a.id AND c.hidden=1)')
    if plan.stage != 'all':
        where.append(f"({CLASSIFICATION_SQL}){'!=' if plan.stage == 'to_catalog' else '='}?")
        values.append('classified' if plan.stage == 'to_catalog' else plan.stage)
    terms = []
    for term in plan.terms:
        terms.append('a.id IN (SELECT asset_id FROM search_text WHERE search_text MATCH ?)')
        values.append(expression(term))
    if terms:
        where.append('(' + (' AND ' if plan.operator == 'and' else ' OR ').join(terms) + ')')
    for term in plan.exclude:
        where.append('a.id NOT IN (SELECT asset_id FROM search_text WHERE search_text MATCH ?)')
        values.append(expression(term))
    if plan.since:
        where.append("""CASE length(json_extract(l.metadata,'$.date'))
            WHEN 4 THEN json_extract(l.metadata,'$.date') || '-12-31'
            WHEN 7 THEN date(json_extract(l.metadata,'$.date') || '-01','+1 month','-1 day')
            ELSE json_extract(l.metadata,'$.date') END >= ?""")
        values.append(plan.since)
    if plan.until:
        where.append("""CASE length(json_extract(l.metadata,'$.date'))
            WHEN 4 THEN json_extract(l.metadata,'$.date') || '-01-01'
            WHEN 7 THEN json_extract(l.metadata,'$.date') || '-01'
            ELSE json_extract(l.metadata,'$.date') END <= ? AND json_extract(l.metadata,'$.date') != ''""")
        values.append(plan.until)
    if plan.place:
        place = normalized(plan.place)
        where.append("""json_extract(l.metadata,'$.place_source')='gps' AND
            (lower(json_extract(l.metadata,'$.place'))=lower(?) OR lower(json_extract(l.metadata,'$.city'))=lower(?))""")
        values.extend([place, place])
    if plan.folder:
        where.append("(instr(lower(l.relative),lower(?))>0 OR instr(lower(coalesce(json_extract(l.metadata,'$.source_folders'),json_extract(l.metadata,'$.source_folder'),'')),lower(?))>0)")
        values.extend([plan.folder,plan.folder])
    if plan.root_id:
        where.append('l.root_id=?')
        values.append(plan.root_id)
    if plan.tag:
        where.append('''(EXISTS(SELECT 1 FROM overrides o WHERE o.asset_id=a.id AND o.tag=? AND included=1)
            OR (EXISTS(SELECT 1 FROM asset_tags t JOIN annotations n ON n.id=t.annotation_id WHERE n.asset_id=a.id
                AND t.tag=? AND n.id=(SELECT max(id) FROM annotations WHERE asset_id=a.id))
                AND NOT EXISTS(SELECT 1 FROM overrides o WHERE o.asset_id=a.id AND o.tag=? AND included=0)))''')
        values.extend([normalized(plan.tag)] * 3)
    clause = ' AND '.join(where)
    order = {'newest': 'day DESC,id', 'oldest': 'day ASC,id', 'name': 'name COLLATE NOCASE,id'}[plan.order]
    with catalog.connect() as db:
        total = db.execute(f'SELECT count(DISTINCT a.id) FROM assets a JOIN file_locations l ON l.asset_id=a.id WHERE {clause}', values).fetchone()[0]
        # Choose one matching location per asset, deterministically, so pagination counts contents rather than copies.
        rows = db.execute(f'''WITH matched AS (
            SELECT a.id,l.relative,l.metadata,l.root_id,ROW_NUMBER() OVER(PARTITION BY a.id ORDER BY l.relative) position
            FROM assets a JOIN file_locations l ON l.asset_id=a.id WHERE {clause})
            SELECT id,relative name,metadata,root_id,json_extract(metadata,'$.date') day FROM matched WHERE position=1
            ORDER BY {order} LIMIT ? OFFSET ?''', [*values, plan.limit, plan.offset]).fetchall()
        results = []
        for row in rows:
            annotation = db.execute('SELECT * FROM annotations WHERE asset_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
            tags = catalog.effective_tags(db, row['id'])
            notes = json.loads(row['metadata'])
            reasons = []
            for term in plan.terms:
                if db.execute('SELECT 1 FROM search_text WHERE asset_id=? AND search_text MATCH ?', (row['id'], expression(term))).fetchone():
                    matching_tags = [tag for tag in tags if tag['tag'] in variants(term)]
                    reasons.extend(f"Tag «{tag['tag']}» · fonte {tag['source']}" for tag in matching_tags)
                    if not matching_tags:
                        reasons.append(f'Descrizione salvata: «{term}»')
            if plan.tag:
                reasons.append('Tag: ' + plan.tag)
            if plan.place:
                reasons.append('Luogo da GPS: ' + notes.get('place', ''))
            if plan.folder:
                reasons.append('Indizio cartella: ' + plan.folder)
            if plan.since or plan.until:
                reasons.append('Data da ' + notes.get('date_source', 'sconosciuta'))
            # Relative folders are useful hints; no absolute PC paths reach clients.
            excluded = db.execute('SELECT excluded_reason FROM assets WHERE id=?', (row['id'],)).fetchone()[0]
            job = db.execute('SELECT state,error,attempts FROM jobs WHERE asset_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
            issue = db.execute('SELECT error FROM archive_errors WHERE asset_id=?', (row['id'],)).fetchone()
            processing = dict(job) if job else {'state': 'pending', 'error': '', 'attempts': 0}
            if issue:
                processing.update(state='error', error=issue[0])
            stage = 'needs_review' if excluded or processing['state'] == 'error' else 'classified' if annotation else 'pending'
            results.append({'id': row['id'], 'kind':notes.get('media_kind','image'), 'excluded_reason': excluded, 'name': notes.get('original_filename') or row['name'].split('/')[-1], 'folder': notes.get('source_folder') or (str(row['name']).rsplit('/', 1)[0] if '/' in row['name'] else ''),
                            'root_id': row['root_id'], 'metadata': notes, 'tags': tags, 'description': annotation['description'] if annotation else '',
                            'annotation': {key: annotation[key] for key in ('model', 'digest', 'quantization', 'prompt_version', 'schema_version', 'seconds')} if annotation else None,
                            'reasons': reasons, 'day': row['day'], 'catalog_state': stage, 'processing': processing,
                            'backup_available': db.execute('SELECT 1 FROM original_backups WHERE asset_id=?', (row['id'],)).fetchone() is not None})
    return {'photos': results, 'total': total, 'limit': plan.limit, 'offset': plan.offset,
            'coverage': catalog.status(), 'plan': plan.model_dump(),
            'notice': 'La ricerca usa tag e descrizioni salvati; attributi separati possono riferirsi a oggetti diversi.'}
