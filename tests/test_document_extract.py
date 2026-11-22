from document_extract import extract


def test_word_and_csv_text_are_indexed_without_altering_the_originals(tmp_path):
    from docx import Document
    from photo_catalog import fingerprint
    word=tmp_path/'spese.docx'
    document=Document(); document.add_paragraph('Spese del viaggio in Macedonia.'); document.add_table(rows=1,cols=1).cell(0,0).text='Skopje 45 euro'; document.save(word)
    before=fingerprint(word)
    result=extract(word,'.docx')
    assert result['state']=='ready' and 'Skopje 45 euro' in result['text']
    assert fingerprint(word)==before
    csv=tmp_path/'spese.csv'; csv.write_text('mese;importo\nottobre;45,50',encoding='utf-8-sig')
    assert 'ottobre' in extract(csv,'.csv')['text']


def test_old_word_is_archived_with_a_visible_text_availability_reason(tmp_path):
    path=tmp_path/'vecchio.doc'; path.write_bytes(b'old-word-file')
    result=extract(path,'.doc')
    assert result['state']=='unavailable' and '.docx' in result['reason']
    assert path.read_bytes()==b'old-word-file'
