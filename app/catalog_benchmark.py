"""Repeatable, isolated photo quality checks; never writes to the user's catalog or images."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import sys
import time

from pydantic import BaseModel, ConfigDict, Field

from photo_annotator import VERSION, FILTER_VERSION, ModelChangedError, PhotoAnnotator
from photo_catalog import fingerprint, normalized


class Check(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    label: str = Field(min_length=1)
    any_tags: list[str] = Field(default_factory=list)
    forbidden_tags: list[str] = Field(default_factory=list)


class Case(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    file: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    checks: list[Check] = Field(min_length=1)


class Suite(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    title: str = Field(min_length=1)
    note: str = Field(min_length=1)
    cases: list[Case] = Field(min_length=1, max_length=200)


def inputs(images: Path, suite: Suite) -> list[Path]:
    """Validate the whole selection before allocating output or calling a model."""
    root = images.resolve(strict=True)
    selected, seen = [], set()
    for case in suite.cases:
        relative = Path(case.file)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(f'Percorso fuori dalla cartella immagini: {case.file}')
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f'Percorso fuori dalla cartella immagini: {case.file}')
        if path in seen:
            raise ValueError(f'Immagine ripetuta: {case.file}')
        seen.add(path)
        for check in case.checks:
            if not check.any_tags and not check.forbidden_tags:
                raise ValueError(f'Controllo senza criteri: {case.file}: {check.label}')
            if any(not normalized(term) for term in check.any_tags + check.forbidden_tags):
                raise ValueError(f'Criterio vuoto: {case.file}: {check.label}')
        selected.append(path)
    return selected


def checks_for(case: Case, tags: list[dict]) -> list[dict]:
    # Whole words/phrases in the saved tags, not a guess based on the dataset class.
    texts = [normalized(tag['tag']) for tag in tags]
    def found(term):
        pattern = r'(?<!\w)' + re.escape(normalized(term)) + r'(?!\w)'
        return any(re.search(pattern, text) for text in texts)
    return [{'label': check.label,
             'passed': (not check.any_tags or any(found(term) for term in check.any_tags))
                       and not any(found(term) for term in check.forbidden_tags)} for check in case.checks]


def cell(value) -> str:
    return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def recheck(report: dict, suite: Suite) -> dict:
    """Explicitly correct reference criteria without changing responses or running inference."""
    if [case.file for case in suite.cases] != [case['file'] for case in report['suite']['cases']]:
        raise ValueError('Il confronto deve riguardare le stesse immagini nello stesso ordine.')
    cases = {case.file: case for case in suite.cases}
    samples = []
    for sample in report['samples']:
        case = cases[sample['file']]
        updated = {**sample, 'reference': case.reference}
        if sample.get('ok'):
            updated['checks'] = checks_for(case, sample['annotation']['tags'])
        samples.append(updated)
    return {**report, 'suite': suite.model_dump(), 'samples': samples, 'references_reapplied': True}


def markdown(report: dict) -> str:
    samples = report['samples']
    successful = [sample for sample in samples if sample.get('ok')]
    elapsed = [sample['seconds'] for sample in successful]
    lines = [f"# {report['suite']['title']}", '', f"Avvio della misura: {report['started_utc']}.", '', report['suite']['note'], '',
             f"Modello: `{report['identity']['name']}` · digest `{report['identity']['digest']}`.",
             f"Versione: `{report['version']}` · filtro `{report['filter_version']}`.", '',
             f"Risposte accettate tecnicamente: {len(successful)}/{len(samples)}; "
             f"immagini previste: {len(report['suite']['cases'])}."]
    if report.get('references_reapplied'):
        lines += ['', 'Riferimenti e controlli riapplicati esplicitamente alle risposte salvate: '
                  'nessuna nuova inferenza e nessuna modifica ai risultati originali.']
    if elapsed:
        lines.append(f'Tempo per foto, controlli inclusi: mediana {statistics.median(elapsed):.2f} s; '
                     f'minimo {min(elapsed):.2f} s; massimo {max(elapsed):.2f} s. Prima chiamata inclusa.')
    lines += ['', 'Le verifiche sui tag sono controlli lessicali limitati, non una misura di accuratezza visiva. '
              'Le note di riferimento non vengono inviate al modello. I tempi dipendono anche dalle cache di Ollama; '
              'un prompt breve su una foto già vista non misura la velocità su una nuova foto.', '',
              '| Foto | Tempo | Tag salvati | Controlli da verificare |', '|---|---:|---|---|']
    for sample in samples:
        annotation = sample.get('annotation', {})
        tags = ', '.join(tag['tag'] for tag in annotation.get('tags', []))
        failed = [check['label'] for check in sample.get('checks', []) if not check['passed']]
        issue = sample.get('error') or '; '.join(failed) or 'nessuno dei controlli fallito'
        lines.append(f"| {cell(sample['file'])} | {sample['seconds']:.2f} s | {cell(tags)} | {cell(issue)} |")
    if any(sample.get('annotation', {}).get('raw', {}).get('_ollama') for sample in samples):
        lines += ['', '## Tempi restituiti da Ollama', '',
                  'Caricamento del modello, elaborazione dell\'input (prompt e immagine), generazione del testo. '
                  'Il tempo per foto sopra include anche controlli di integrità e metadati. '
                  'Le fasi possono riusare cache: questi dati non identificano da soli una prova a freddo. '
                  'Una metrica assente è indicata con —.', '',
                  '| Foto | Caricamento | Input | Generazione | Token input / cache / generati |',
                  '|---|---:|---:|---:|---|']
        for sample in samples:
            metrics = sample.get('annotation', {}).get('raw', {}).get('_ollama', {})
            times = [f'{metrics[key]:.3f} s' if key in metrics else '—'
                     for key in ('load_seconds', 'prompt_seconds', 'generation_seconds')]
            tokens = ' / '.join(str(metrics.get(key, '—'))
                               for key in ('prompt_tokens', 'prompt_cached_tokens', 'generated_tokens'))
            lines.append(f"| {cell(sample['file'])} | {' | '.join(times)} | {tokens} |")
    lines += ['', '## Riferimenti e descrizioni', '']
    for sample in samples:
        lines += [f"### {cell(sample['file'])}", '', f"Riferimento visivo: {sample['reference']}", '',
                  'Qwen: ' + sample.get('annotation', {}).get('description', sample.get('error', '')), '']
    return '\n'.join(lines)


def checkpoint(output: Path, report: dict):
    # Same-directory replacement leaves the previous complete checkpoint readable on interruption.
    temporary = output / 'results.json.tmp'
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output / 'results.json')
    (output / 'report.md').write_text(markdown(report), encoding='utf-8')


async def run(images: Path, suite: Suite, output: Path, annotator=None) -> dict:
    paths = inputs(images, suite)
    if output.resolve().is_relative_to(images.resolve()):
        raise ValueError('Salva il benchmark fuori dalla cartella immagini.')
    output.mkdir(parents=True, exist_ok=False)
    annotator = annotator or PhotoAnnotator()
    identity = await annotator.verify()
    report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'identity': identity,
              'version': VERSION, 'filter_version': FILTER_VERSION, 'suite': suite.model_dump(), 'samples': []}
    checkpoint(output, report)
    for case, path in zip(suite.cases, paths, strict=True):
        print(f'Analisi {case.file}', flush=True)
        started = time.perf_counter()
        sample = {'file': case.file, 'reference': case.reference, 'ok': False}
        changed_model = False
        try:
            before = await asyncio.to_thread(fingerprint, path)
            annotation = await annotator.annotate(path)
            after = await asyncio.to_thread(fingerprint, path)
            if before != after:
                raise ValueError('Immagine cambiata durante la prova: risultato escluso.')
            sample.update(sha256=before, annotation=annotation, ok=True, checks=checks_for(case, annotation['tags']))
        except Exception as error:
            sample['error'] = f'{type(error).__name__}: {error}'
            changed_model = isinstance(error, ModelChangedError)
        sample['seconds'] = time.perf_counter() - started
        report['samples'].append(sample)
        checkpoint(output, report)
        print(json.dumps({key: sample[key] for key in ('file', 'seconds', 'ok', 'error', 'checks') if key in sample},
                         ensure_ascii=False), flush=True)
        if changed_model:
            break
    return report


async def main():
    parser = argparse.ArgumentParser(description='Prova foto isolata; nessuna modifica a catalogo, modelli o originali.')
    commands = parser.add_subparsers(dest='command', required=True)
    execute = commands.add_parser('run')
    execute.add_argument('--images', type=Path, required=True)
    execute.add_argument('--suite', type=Path, required=True)
    execute.add_argument('--output', type=Path, required=True, help='Nuova cartella, esterna alle immagini')
    replay = commands.add_parser('report', help='Rigenera il Markdown dai risultati, senza inferenza')
    replay.add_argument('results', type=Path)
    replay.add_argument('--suite', type=Path, help='Riapplica riferimenti corretti alle stesse foto, senza inferenza')
    replay.add_argument('--output', type=Path, required=True, help='Nuovo file Markdown')
    args = parser.parse_args()
    if args.command == 'report':
        report = json.loads(args.results.read_text(encoding='utf-8'))
        if args.suite:
            report = recheck(report, Suite.model_validate_json(args.suite.read_text(encoding='utf-8')))
        with args.output.open('x', encoding='utf-8') as target:
            target.write(markdown(report))
    else:
        suite = Suite.model_validate_json(args.suite.read_text(encoding='utf-8'))
        report = await run(args.images, suite, args.output)
        if len(report['samples']) != len(suite.cases) or not all(sample['ok'] for sample in report['samples']):
            return 1
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(asyncio.run(main()))
