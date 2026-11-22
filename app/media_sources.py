"""Provenance labels and safe relative destinations, independent of media indexing."""
import re
from pathlib import PurePosixPath


def document_category(name):
    extension=name.rsplit('.',1)[-1].casefold()
    return {'pdf':'pdf','xlsx':'excel','xls':'excel','docx':'word','doc':'word','csv':'csv','txt':'txt'}.get(extension,'')


def document_label(category):
    return {'pdf':'PDF','excel':'Excel','word':'Word','csv':'CSV','txt':'TXT'}.get(category,'Documenti')


def source_group(folder):
    parts = re.split(r'[/\\:]+', folder.casefold())
    if any(part in ('whatsapp','com.whatsapp','com.whatsapp.w4b') or part.startswith('whatsapp ') for part in parts):
        return 'whatsapp'
    if any(part in ('telegram','org.telegram.messenger','org.telegram.messenger.web') or part.startswith('telegram ') for part in parts):
        return 'telegram'
    return 'normal'


def source_parts(folder):
    group = source_group(folder)
    parts = re.split(r'[/\\:]+', folder)
    for index, part in enumerate(parts):
        if part.casefold() == group:
            return [value for value in parts[index+1:] if value not in ('','.','..')]
    for index, part in enumerate(parts):
        if part.casefold().startswith(group+' '):
            return [value for value in parts[index:] if value not in ('','.','..')]
    return []


def source_tag(group):
    return {'whatsapp':'WhatsApp','telegram':'Telegram'}.get(group,'')
