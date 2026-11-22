from pathlib import Path
from contextlib import closing
import subprocess

import pytest

from photo_catalog import PhotoCatalog, fingerprint
from photo_annotator import VERSION
from video_tools import binary, probe, preview, storyboard
from phone_catalog import snapshot
from catalog_organize import CatalogOrganization, BulkEdit
from photo_search import search, SearchPlan


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / 'video.mp4'
    subprocess.run([binary(), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=160x120:d=2',
                    '-metadata', 'creation_time=2025-05-10T10:00:00Z', '-c:v', 'mpeg4', str(path)], check=True, capture_output=True)
    return path


def test_video_metadata_and_bounded_previews_do_not_change_the_original(clip):
    before = fingerprint(clip)
    width, height, notes = probe(clip)
    assert (width,height) == (160,120)
    assert notes['duration_seconds'] == 2
    assert notes['date'] == '2025-05-10'
    assert notes['date_source'] == 'video_metadata'
    picture = preview(clip, 128)
    assert max(picture.size) <= 128
    image, moments = storyboard(clip, 128)
    assert len(moments) == 3 and moments == sorted(moments)
    assert image.startswith(b'\xff\xd8') and len(image)<100000
    assert fingerprint(clip) == before


def test_video_is_searchable_in_a_mixed_album_and_exported_to_the_phone(clip,tmp_path):
    catalog = PhotoCatalog(tmp_path/'index'/'catalog.sqlite')
    catalog.add_root(clip.parent)
    catalog.scan(VERSION,stable_seconds=0)
    sha = fingerprint(clip)
    org = CatalogOrganization(catalog)
    org.apply(org.preview(BulkEdit(ids=[sha],tags='Skopje, Macedonia',album='Viaggio a Skopje'))['preview_id'])
    result = search(catalog,SearchPlan(kind='video',tag='skopje'))
    assert len(result['photos']) == 1 and result['photos'][0]['kind'] == 'video'
    path = snapshot(catalog,'phone')
    try:
        import sqlite3
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('SELECT kind FROM photos WHERE id=?',(sha,)).fetchone()[0]=='video'
            assert db.execute('SELECT name FROM albums').fetchone()[0]=='Viaggio a Skopje'
            assert db.execute('SELECT asset_id FROM album_items').fetchone()[0]==sha
    finally:
        path.unlink()


def test_unreadable_video_is_reported_without_any_rewrite(tmp_path):
    path=tmp_path/'broken.mp4'
    path.write_bytes(b'not a video')
    with pytest.raises(ValueError,match='Nessuna traccia video'):
        probe(path)
    assert path.read_bytes()==b'not a video'
