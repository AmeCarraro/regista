import hashlib
from datetime import date

from fastapi import HTTPException
import pytest

import archive_cleanup
from archive_cleanup import ArchiveCleanup, Candidate, CleanupChunk, CleanupResult, CleanupTarget, Matched
from import_batches import ImportManifest, StartImport
from test_import_batches import batches,sample,begin,send


def ready_cleanup(batches,tmp_path):
    path,item=sample(tmp_path)
    batch=begin(batches)
    send(batches,batch,path,item)
    batches.finalize_sync(batch)
    cleanup=ArchiveCleanup(batches)
    job=cleanup.prepare(batch,'phone-1')['id']
    batches.pool.submit(lambda:None).result(timeout=5)
    candidate=Candidate(media=item.media,stamp=item.stamp,sha256=item.sha256,name=item.name,folder=item.folder,kind=item.kind)
    return cleanup,batch,job,candidate


def test_pc_confirmation_and_android_consent_are_separate_required_steps(batches,tmp_path):
    cleanup,batch,job,item=ready_cleanup(batches,tmp_path)
    assert cleanup.pending('phone-1')['job']['state']=='finding'
    cleanup.matched('phone-1',Matched(job_id=job,files=[item]))
    with pytest.raises(HTTPException,match='conferma'):
        cleanup.authorize('phone-1',CleanupChunk(job_id=job,media=[item.media]))
    cleanup.confirm(job,True)
    allowed=cleanup.authorize('phone-1',CleanupChunk(job_id=job,media=[item.media]))
    assert allowed['authorized'] and allowed['requires_android_confirmation']
    assert allowed['files'][0]['sha256']==item.sha256


def test_only_files_in_the_chosen_archive_can_be_proposed(batches,tmp_path):
    cleanup,batch,job,item=ready_cleanup(batches,tmp_path)
    unrelated=item.model_copy(update={'sha256':'0'*64})
    with pytest.raises(HTTPException):
        cleanup.matched('phone-1',Matched(job_id=job,files=[unrelated]))
    assert cleanup.status(job)['state']=='finding'


def test_missing_normal_copy_blocks_phone_deletion_even_with_valid_zip(batches,tmp_path):
    cleanup,batch,job,item=ready_cleanup(batches,tmp_path)
    cleanup.matched('phone-1',Matched(job_id=job,files=[item]))
    batches.normal_path(item.sha256).unlink()
    with pytest.raises(HTTPException,match='copia normale'):
        cleanup.confirm(job,True)
    assert cleanup.status(job)['state']=='matched'


def test_staged_copy_does_not_count_as_published_pc_backup(batches, tmp_path):
    cleanup, batch, job, item = ready_cleanup(batches, tmp_path)
    cleanup.matched('phone-1', Matched(job_id=job, files=[item]))
    batches.staging.mkdir(exist_ok=True)
    staged = batches.staging / 'in-progress.png'
    batches.normal_path(item.sha256).replace(staged)
    with batches.connect() as db:
        db.execute('UPDATE normal_files SET path=? WHERE sha256=?', (str(staged), item.sha256))
    with pytest.raises(HTTPException, match='copia normale'):
        cleanup.confirm(job, True)


def test_corrupt_zip_blocks_phone_deletion_even_with_valid_normal_copy(batches,tmp_path):
    cleanup,batch,job,item=ready_cleanup(batches,tmp_path)
    cleanup.matched('phone-1',Matched(job_id=job,files=[item]))
    batches.zip_path(batch).write_bytes(b'changed')
    with pytest.raises(HTTPException,match='ZIP'):
        cleanup.confirm(job,True)


def test_android_result_never_removes_pc_photos_tags_or_archives(batches,tmp_path):
    cleanup,batch,job,item=ready_cleanup(batches,tmp_path)
    archive=batches.zip_path(batch)
    immutable=hashlib.sha256(archive.read_bytes()).hexdigest()
    batches.catalog.override(item.sha256,'Giappone',True)
    cleanup.matched('phone-1',Matched(job_id=job,files=[item]))
    cleanup.confirm(job,True)
    cleanup.authorize('phone-1',CleanupChunk(job_id=job,media=[item.media]))
    result=cleanup.result('phone-1',CleanupResult(job_id=job,media=[item.media],done=True))
    assert result['state']=='finished' and result['removed']==1
    assert batches.catalog.path_of(item.sha256).is_file()
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==immutable
    with batches.catalog.connect() as db:
        assert any(tag['tag']=='giappone' for tag in batches.catalog.effective_tags(db,item.sha256))


def test_another_phone_and_cancelled_requests_cannot_authorize_deletion(batches,tmp_path):
    cleanup,batch,job,item=ready_cleanup(batches,tmp_path)
    with pytest.raises(HTTPException):
        cleanup.matched('other-phone',Matched(job_id=job,files=[item]))
    cleanup.matched('phone-1',Matched(job_id=job,files=[item]))
    cleanup.confirm(job,False)
    assert cleanup.pending('phone-1')['job'] is None
    with pytest.raises(HTTPException):
        cleanup.authorize('phone-1',CleanupChunk(job_id=job,media=[item.media]))


def test_revoke_cancels_pending_cleanup_without_forgetting_archive(batches,tmp_path):
    cleanup,batch,job,item=ready_cleanup(batches,tmp_path)
    cleanup.revoke('phone-1')
    assert cleanup.status(job)['state']=='cancelled'
    assert batches.status(batch)['zip_ready']
    assert batches.catalog.path_of(item.sha256).is_file()


def test_whatsapp_cleanup_filters_exact_origins_dates_and_individual_choices(batches, tmp_path):
    photo, camera = sample(tmp_path)
    normal_batch = begin(batches)
    send(batches, normal_batch, photo, camera)
    batches.finalize_sync(normal_batch)
    archive = batches.zip_path(normal_batch)
    original_zip = archive.read_bytes()
    folder = 'Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images'
    older, kept, recent, undated = [
        camera.model_copy(update={'media': f'tree:{label}', 'name': f'{label}.png', 'folder': folder})
        for label in ('older', 'kept', 'recent', 'undated')
    ]
    video = camera.model_copy(update={'media': 'tree:video', 'name': 'received.mp4', 'kind': 'video', 'folder': folder})
    sync = batches.start('phone-1', StartImport(work_id='wa', total=5, source='whatsapp'))['id']
    manifest = ImportManifest(batch_id=sync, files=[older, kept, recent, undated, video])
    assert batches.manifest('phone-1', manifest)['wanted'] == []
    assert not batches.finalize_sync(sync)['zip_ready']

    cleanup = ArchiveCleanup(batches)
    target = CleanupTarget(device='phone-1', source='whatsapp', kind='image', until=date(2024, 12, 31))
    job = cleanup.prepare('', target)['id']
    batches.pool.submit(lambda: None).result(timeout=5)
    candidates = cleanup.candidates('phone-1', job, 0)['files']
    assert {row['media'] for row in candidates} == {item.media for item in (older, kept, recent, undated)}
    receipts = {row['media']: row for row in candidates}

    def candidate(item, day, source='file'):
        return Candidate(**receipts[item.media], day=day, date_source=source, method='folder')

    for outside in (candidate(recent, '2025-01-01'), candidate(undated, None, ''),
                    candidate(older, '2024-12-30', 'capture')):
        with pytest.raises(HTTPException, match='data'):
            cleanup.matched('phone-1', Matched(job_id=job, files=[outside], finished=False))
    cleanup.matched('phone-1', Matched(job_id=job, files=[candidate(older, '2024-12-31'), candidate(kept, '2023-08-03')]))
    assert cleanup.confirm(job, True, keep=[kept.media])['selected'] == 1
    with pytest.raises(HTTPException, match='confermata'):
        cleanup.authorize('phone-1', CleanupChunk(job_id=job, media=[older.media, kept.media]))
    result = cleanup.authorize('phone-1', CleanupChunk(job_id=job, media=[older.media]))
    assert [item['media'] for item in result['files']] == [older.media]
    assert archive.read_bytes() == original_zip
    assert batches.catalog.path_of(camera.sha256).is_file()


def test_only_selected_files_and_current_pc_copies_allow_authorization(batches, tmp_path):
    cleanup, batch, job, item = ready_cleanup(batches, tmp_path)
    cleanup.matched('phone-1', Matched(job_id=job, files=[item]))
    with pytest.raises(HTTPException, match='almeno un file'):
        cleanup.confirm(job, True, only=[])
    cleanup.confirm(job, True, only=[item.media])
    batches.zip_path(batch).write_bytes(b'changed after confirmation')
    with pytest.raises(HTTPException, match='ZIP'):
        cleanup.authorize('phone-1', CleanupChunk(job_id=job, media=[item.media]))


def many_candidates(batches, tmp_path, total):
    batch = begin(batches, total=total)
    photo, first = sample(tmp_path, media='image:external:00')
    send(batches, batch, photo, first)
    others = [first.model_copy(update={'media': f'image:external:{i:02}', 'name': f'{i:02}.png'})
              for i in range(1, total)]
    batches.manifest('phone-1', ImportManifest(batch_id=batch, files=others))
    assert batches.finalize_sync(batch)['zip_ready']
    cleanup = ArchiveCleanup(batches)
    job = cleanup.prepare('', 'phone-1')['id']
    batches.pool.submit(lambda: None).result(timeout=5)
    return cleanup, job


def test_cleanup_checkpoints_empty_pages_and_stops_at_each_quarter(batches, tmp_path, monkeypatch):
    monkeypatch.setattr(archive_cleanup, 'PAGE', 2)
    cleanup, job = many_candidates(batches, tmp_path, 12)
    pending = cleanup.pending('phone-1')['job']
    assert (pending['scanned'], pending['scan_total']) == (0, 12)
    page = cleanup.candidates('phone-1', job, 0, checkpoint=True)['files']
    assert len(page) == 2
    with pytest.raises(HTTPException, match='ripresa'):
        cleanup.matched('phone-1', Matched(job_id=job, files=[], offset=2))
    first = cleanup.matched('phone-1', Matched(job_id=job, files=[], offset=0))
    assert first['scanned'] == 2 and not first['finished']
    cleanup = ArchiveCleanup(batches)
    assert cleanup.pending('phone-1')['job']['scanned'] == 2
    assert cleanup.matched('phone-1', Matched(job_id=job, files=[], offset=0))['scanned'] == 2
    page = cleanup.candidates('phone-1', job, 2, checkpoint=True)['files']
    assert len(page) == 1
    item = Candidate(**page[0])
    assert cleanup.matched('phone-1', Matched(job_id=job, files=[item], offset=2))['finished']
    assert cleanup.status(job)['scanned'] == 3
    for review, boundary in enumerate((6, 9, 12)):
        current = cleanup.continue_review(job, review)
        assert current['count'] == 0
        assert current['scanned'] == boundary - 3
        cleanup.matched('phone-1', Matched(job_id=job, files=[], offset=boundary-3))
        cleanup.matched('phone-1', Matched(job_id=job, files=[], offset=boundary-1))
        assert cleanup.status(job)['state'] == 'matched'
        assert cleanup.status(job)['scanned'] == boundary
    with pytest.raises(HTTPException, match='altri file'):
        cleanup.continue_review(job, 3)


def test_cleanup_can_review_partial_results_without_reusing_removal_consent(batches, tmp_path, monkeypatch):
    monkeypatch.setattr(archive_cleanup, 'PAGE', 2)
    cleanup, job = many_candidates(batches, tmp_path, 12)
    page = cleanup.candidates('phone-1', job, 0, checkpoint=True)['files']
    keep, remove = [Candidate(**item, original=str(i + 1) * 64) for i, item in enumerate(page)]
    cleanup.matched('phone-1', Matched(job_id=job, files=[keep, remove], offset=0))
    assert cleanup.pause_review(job, 0)['count'] == 2
    assert cleanup.confirm(job, True, keep=[keep.media])['selected'] == 1
    cleanup.authorize('phone-1', CleanupChunk(job_id=job, media=[remove.media]))
    result = CleanupResult(job_id=job, media=[remove.media])
    assert cleanup.result('phone-1', result)['state'] == 'reviewed'
    assert cleanup.continue_review(job, 0)['scanned'] == 2
    assert cleanup.result('phone-1', result)['removed'] == 1
    page = cleanup.candidates('phone-1', job, 2, checkpoint=True)['files']
    duplicate = Candidate(**page[0], original=keep.original)
    cleanup.matched('phone-1', Matched(job_id=job, files=[duplicate], offset=2))
    current = cleanup.status(job)
    assert current['state'] == 'matched' and current['count'] == 0 and current['removed'] == 1
    with pytest.raises(HTTPException, match='altro lotto'):
        cleanup.confirm(job, True, review=0)


def test_existing_legacy_review_recovers_the_last_saved_page(batches, tmp_path, monkeypatch):
    monkeypatch.setattr(archive_cleanup, 'PAGE', 2)
    cleanup, job = many_candidates(batches, tmp_path, 12)
    photo = Candidate(**cleanup.candidates('phone-1', job, 0)['files'][0])
    cleanup.matched('phone-1', Matched(job_id=job, files=[photo], finished=False))
    with batches.connect() as db:
        db.execute('DROP INDEX cleanup_originals')
        for column in ('scanned', 'scan_total', 'review'):
            db.execute(f'ALTER TABLE cleanup_jobs DROP COLUMN {column}')
        for column in ('reviewed', 'original'):
            db.execute(f'ALTER TABLE cleanup_files DROP COLUMN {column}')
    cleanup = ArchiveCleanup(batches)
    recovered = cleanup.status(job)
    assert (recovered['state'], recovered['count'], recovered['scanned'], recovered['scan_total']) == ('finding', 1, 2, 12)
    assert cleanup.pause_review(job, 0)['files'][0]['media'] == photo.media
