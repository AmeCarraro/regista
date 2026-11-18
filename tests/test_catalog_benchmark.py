import asyncio
import json
from pathlib import Path

from PIL import Image
import pytest

from catalog_benchmark import Case, Check, Suite, checks_for, inputs, markdown, recheck, run
from photo_annotator import ModelChangedError
from photo_catalog import fingerprint


def suite(*names):
    return Suite(title='Prova', note='Controlli limitati, non accuratezza.', cases=[
        Case(file=name, reference='Un cane visibile.', checks=[Check(label='cane nei tag', any_tags=['cane'])])
        for name in names])


def picture(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (32, 24), 'red').save(path)
    return path


class Annotator:
    def __init__(self, failure=None):
        self.calls = []
        self.verifications = 0
        self.failure = failure

    async def verify(self):
        self.verifications += 1
        return {'name': 'test', 'digest': 'test-digest'}

    async def annotate(self, path):
        self.calls.append(path.name)
        if self.failure and len(self.calls) == 1:
            raise self.failure
        return {'description': 'Un cane.', 'tags': [{'tag': 'cane', 'category': 'animal'}], 'raw': {}}


def test_benchmark_only_reads_selected_images_and_checkpoint_can_be_reported_without_inference(tmp_path):
    images = tmp_path / 'photos'
    selected = picture(images, 'one.png')
    picture(images, 'not-selected.png')
    before = fingerprint(selected)
    output = tmp_path / 'benchmark'
    annotator = Annotator()
    report = asyncio.run(run(images, suite('one.png'), output, annotator))
    assert annotator.calls == ['one.png'] and annotator.verifications == 1
    assert fingerprint(selected) == before == report['samples'][0]['sha256']
    assert sorted(path.name for path in output.iterdir()) == ['report.md', 'results.json']
    persisted = json.loads((output / 'results.json').read_text(encoding='utf-8'))
    assert markdown(persisted) == (output / 'report.md').read_text(encoding='utf-8')
    assert persisted['samples'][0]['checks'] == [{'label': 'cane nei tag', 'passed': True}]
    corrected = suite('one.png')
    corrected.cases[0].checks = [Check(label='gatto nei tag', any_tags=['gatto'])]
    revised = recheck(persisted, corrected)
    assert revised['samples'][0]['checks'] == [{'label': 'gatto nei tag', 'passed': False}]
    assert revised['samples'][0]['annotation'] == persisted['samples'][0]['annotation']
    assert persisted['samples'][0]['checks'][0]['passed'] is True
    assert 'nessuna nuova inferenza' in markdown(revised)
    with pytest.raises(ValueError, match='stesse immagini'):
        recheck(persisted, suite('different.png'))
    with pytest.raises(FileExistsError):
        asyncio.run(run(images, suite('one.png'), output, annotator))
    assert annotator.verifications == 1


@pytest.mark.parametrize('failure', [ValueError('Risposta incompleta'), TimeoutError('Tempo scaduto')])
def test_failed_photo_is_recorded_once_and_next_photo_is_tested(tmp_path, failure):
    images = tmp_path / 'photos'
    picture(images, 'one.png')
    picture(images, 'two.png')
    annotator = Annotator(failure)
    report = asyncio.run(run(images, suite('one.png', 'two.png'), tmp_path / 'benchmark', annotator))
    assert annotator.calls == ['one.png', 'two.png']
    assert [sample['ok'] for sample in report['samples']] == [False, True]
    assert str(failure) in report['samples'][0]['error']
    assert 'Risposte accettate tecnicamente: 1/2' in markdown(report)


def test_digest_change_stops_the_benchmark_without_running_more_images(tmp_path):
    images = tmp_path / 'photos'
    picture(images, 'one.png')
    picture(images, 'two.png')
    annotator = Annotator(ModelChangedError('Digest cambiato'))
    report = asyncio.run(run(images, suite('one.png', 'two.png'), tmp_path / 'benchmark', annotator))
    assert annotator.calls == ['one.png']
    assert len(report['samples']) == 1 and not report['samples'][0]['ok']
    assert 'immagini previste: 2' in markdown(report)


def test_lexical_checks_use_word_boundaries_and_do_not_equate_technical_success_with_quality():
    case = Case(file='test.png', reference='Cane.', checks=[
        Check(label='cane', any_tags=['cane']), Check(label='nessun computer', forbidden_tags=['computer'])])
    assert checks_for(case, [{'tag': 'canestro'}, {'tag': 'computer'}]) == [
        {'label': 'cane', 'passed': False}, {'label': 'nessun computer', 'passed': False}]
    assert checks_for(case, [{'tag': 'CANE nero'}]) == [
        {'label': 'cane', 'passed': True}, {'label': 'nessun computer', 'passed': True}]


@pytest.mark.parametrize('name', ['../outside.png', 'one.png/../../outside.png'])
def test_manifest_cannot_escape_the_selected_images_folder(tmp_path, name):
    images = tmp_path / 'photos'
    images.mkdir()
    picture(tmp_path, 'outside.png')
    with pytest.raises(ValueError, match='fuori'):
        inputs(images, suite(name))


def test_all_inputs_are_validated_before_any_inference_or_output(tmp_path):
    images = tmp_path / 'photos'
    picture(images, 'one.png')
    annotator = Annotator()
    output = tmp_path / 'benchmark'
    with pytest.raises(FileNotFoundError):
        asyncio.run(run(images, suite('one.png', 'missing.png'), output, annotator))
    assert annotator.calls == [] and annotator.verifications == 0 and not output.exists()
    with pytest.raises(ValueError, match='ripetuta'):
        inputs(images, suite('one.png', 'one.png'))
    with pytest.raises(ValueError, match='fuori dalla cartella immagini'):
        asyncio.run(run(images, suite('one.png'), images / 'benchmark', annotator))
    empty_check = suite('one.png')
    empty_check.cases[0].checks = [Check(label='vuoto')]
    with pytest.raises(ValueError, match='senza criteri'):
        inputs(images, empty_check)


def test_recorded_public_suite_contains_ten_distinct_images():
    data = Path(__file__).parent / 'fixtures' / 'qwen-foto-010-019.json'
    cases = Suite.model_validate_json(data.read_text(encoding='utf-8'))
    assert [case.file for case in cases.cases] == [f'{number:03d}.jpg' for number in range(10, 20)]
