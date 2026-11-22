"""Read text in a short-lived worker. This file never saves or modifies an original."""
import json
from pathlib import Path
import sys
import zipfile

MAX_TEXT = 500_000


def extract(path, extension):
    path = Path(path)
    if path.stat().st_size > 64*1024**2:
        return {'text':'','state':'unavailable','reason':'Documento archiviato; oltre il limite di 64 MB per l’estrazione del testo.'}
    if extension in ('.xlsx','.docx'):
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries)>20000 or sum(item.file_size for item in entries)>256*1024**2:
                raise ValueError('Documento archiviato; struttura troppo grande per l’indicizzazione.')
    pieces, length, truncated = [], 0, False
    def add(value):
        nonlocal length, truncated
        if value is None: return
        value = str(value)
        if length+len(value)>MAX_TEXT:
            pieces.append(value[:max(0,MAX_TEXT-length)])
            truncated = True
            raise StopIteration
        pieces.append(value)
        length += len(value)+1
    try:
        if extension == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(path,strict=False)
            if reader.is_encrypted and not reader.decrypt(''):
                return {'text':'','state':'protected','reason':'PDF protetto: originale archiviato, ricercabile per nome e metadati.'}
            for page in reader.pages[:1000]:
                add(page.extract_text() or '')
            if len(reader.pages)>1000: truncated=True
        elif extension == '.xlsx':
            from openpyxl import load_workbook
            book = load_workbook(path,read_only=True,data_only=False,keep_links=False)
            try:
                for sheet in book.worksheets:
                    add(sheet.title)
                    for row in sheet.iter_rows(values_only=True):
                        for value in row: add(value)
            finally:
                book.close()
        elif extension == '.xls':
            import xlrd
            book = xlrd.open_workbook(path,on_demand=True,ragged_rows=True)
            try:
                for sheet in book.sheets():
                    add(sheet.name)
                    for row in range(sheet.nrows):
                        for value in sheet.row_values(row): add(value)
            finally:
                book.release_resources()
        elif extension == '.docx':
            from docx import Document
            document=Document(path)
            for paragraph in document.paragraphs: add(paragraph.text)
            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells: add(cell.text)
        elif extension in ('.csv','.txt'):
            data=path.read_bytes()[:2*MAX_TEXT]
            codec='utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
            try: text=data.decode(codec)
            except UnicodeError: text=data.decode('cp1252',errors='replace')
            add(text)
            if path.stat().st_size>len(data): truncated=True
        else:
            return {'text':'','state':'unavailable','reason':'Formato .doc archiviato. Per indicizzare il contenuto usa una copia in .docx.'}
    except StopIteration:
        pass
    text='\n'.join(pieces).strip()[:MAX_TEXT]
    return {'text':text,'state':'partial' if truncated else 'ready' if text else 'no_text',
            'reason':'Testo parziale: raggiunto il limite di indicizzazione.' if truncated else '' if text else 'Testo non disponibile. Il documento resta ricercabile per nome e metadati; non è stato eseguito OCR.'}


if __name__ == '__main__':
    try:
        result=extract(sys.argv[1],sys.argv[2])
    except Exception as error:
        result={'text':'','state':'error','reason':str(error)[:500]}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))
