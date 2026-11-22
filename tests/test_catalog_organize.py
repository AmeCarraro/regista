import json

from PIL import Image
import pytest

from catalog_organize import BulkEdit,CatalogOrganization
from photo_catalog import PhotoCatalog
from photo_search import SearchPlan,search


@pytest.fixture
def library(tmp_path):
    root=tmp_path/'foto'
    root.mkdir()
    catalog=PhotoCatalog(tmp_path/'index/catalog.sqlite')
    root_id=catalog.add_root(root)
    ids=[]
    for index,color in enumerate(['red','blue','green']):
        path=root/f'2026-04-{index+1:02d}.png'
        Image.new('RGB',(8,8),color).save(path)
        ids.append(catalog.register(root_id,path,'test')[0])
    return catalog,ids


def test_bulk_preview_is_read_only_and_tags_are_split_and_deduplicated(library):
    catalog,ids=library
    organization=CatalogOrganization(catalog)
    preview=organization.preview(BulkEdit(ids=ids[:2],tags=' Skopje, Macedonia, skopje '))
    assert preview['count']==2 and preview['tags']==['skopje','macedonia']
    assert search(catalog,SearchPlan(tag='skopje'))['total']==0
    organization.apply(preview['preview_id'])
    assert search(catalog,SearchPlan(tag='skopje'))['total']==2
    assert search(catalog,SearchPlan(tag='macedonia'))['total']==2


def test_date_selection_is_frozen_at_preview_and_includes_both_boundaries(library):
    catalog,ids=library
    organization=CatalogOrganization(catalog)
    preview=organization.preview(BulkEdit(select_all=True,plan=SearchPlan(since='2026-04-01',until='2026-04-02'),tags='Viaggio'))
    assert preview['count']==2
    assert organization.apply(preview['preview_id'])['updated']==2
    found={row['id'] for row in search(catalog,SearchPlan(tag='viaggio'))['photos']}
    assert found==set(ids[:2])


def test_album_is_a_reference_and_general_library_keeps_the_same_files(library):
    catalog,ids=library
    organization=CatalogOrganization(catalog)
    before={asset:catalog.path_of(asset).read_bytes() for asset in ids}
    archives={asset:catalog.archive.path(asset).read_bytes() for asset in ids}
    preview=organization.preview(BulkEdit(ids=ids[:2],tags='Giappone',album='Viaggio in Giappone'))
    album=organization.apply(preview['preview_id'])['album_id']
    assert search(catalog,SearchPlan())['total']==3
    assert search(catalog,SearchPlan(album=album))['total']==2
    for asset in ids:
        assert catalog.path_of(asset).read_bytes()==before[asset]
        assert catalog.archive.path(asset).read_bytes()==archives[asset]


def test_hiding_album_changes_default_view_without_forgetting_media(library):
    catalog,ids=library
    organization=CatalogOrganization(catalog)
    preview=organization.preview(BulkEdit(ids=ids[:2],album='Skopje'))
    album=organization.apply(preview['preview_id'])['album_id']
    organization.hide_album(album,True)
    assert search(catalog,SearchPlan())['total']==1
    assert search(catalog,SearchPlan(include_hidden=True))['total']==3
    assert search(catalog,SearchPlan(album=album))['total']==2
    assert catalog.status()['discovered']==3
    organization.hide_album(album,False)
    assert search(catalog,SearchPlan())['total']==3


def test_individual_hide_and_restore_preserve_tags_and_originals(library):
    catalog,ids=library
    organization=CatalogOrganization(catalog)
    preview=organization.preview(BulkEdit(ids=ids[:1],tags='Macedonia',hidden=True))
    organization.apply(preview['preview_id'])
    assert search(catalog,SearchPlan(tag='macedonia'))['total']==0
    assert search(catalog,SearchPlan(tag='macedonia',include_hidden=True))['total']==1
    preview=organization.preview(BulkEdit(ids=ids[:1],hidden=False))
    organization.apply(preview['preview_id'])
    assert search(catalog,SearchPlan(tag='macedonia'))['total']==1
    assert catalog.path_of(ids[0]).is_file()


def test_preview_cannot_be_replayed_or_implicitly_select_everything(library):
    catalog,ids=library
    organization=CatalogOrganization(catalog)
    with pytest.raises(ValueError):
        organization.preview(BulkEdit(tags='Giappone'))
    preview=organization.preview(BulkEdit(ids=ids[:1],tags='Giappone'))
    organization.apply(preview['preview_id'])
    with pytest.raises(ValueError):
        organization.apply(preview['preview_id'])


def test_video_and_photo_can_share_tags_and_the_same_album(library,tmp_path):
    catalog,ids=library
    root=catalog.roots(local=True)[0]
    path=tmp_path/'foto/2026-04-02.mp4'
    path.write_bytes(b'original-video')
    video=catalog.register(root['id'],path,'test')[0]
    organization=CatalogOrganization(catalog)
    preview=organization.preview(BulkEdit(ids=[ids[0],video],tags='Skopje',album='Skopje'))
    album=organization.apply(preview['preview_id'])['album_id']
    assert search(catalog,SearchPlan(album=album))['total']==2
    assert search(catalog,SearchPlan(album=album,kind='video'))['total']==1
    assert search(catalog,SearchPlan(album=album,kind='image'))['total']==1
