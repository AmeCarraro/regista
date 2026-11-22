import hashlib
import json

from fastapi import HTTPException
import pytest

from archive_cleanup import ArchiveCleanup,Candidate,Matched,CleanupChunk,CleanupResult
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
