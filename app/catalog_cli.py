"""Diagnostics: python app/catalog_cli.py --database build/prova/catalog.sqlite scan foto-prova."""
import argparse
import asyncio
import json

from index_jobs import IndexJobs
from photo_annotator import PhotoAnnotator, VERSION
from photo_catalog import PhotoCatalog
from photo_search import SearchPlan, search


async def main():
    parser = argparse.ArgumentParser(description='Catalogo persistente Regista. Scansione e analisi sono comandi separati.')
    parser.add_argument('--database', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('scan')
    scan.add_argument('folder')
    commands.add_parser('status')
    commands.add_parser('verify-model')
    run = commands.add_parser('run')
    run.add_argument('--max-photos', type=int, default=10)
    find = commands.add_parser('search')
    find.add_argument('terms', nargs='*')
    find.add_argument('--folder', default='')
    find.add_argument('--place', default='')
    find.add_argument('--since', default='')
    find.add_argument('--until', default='')
    args = parser.parse_args()
    catalog = PhotoCatalog(args.database)
    annotator = PhotoAnnotator()
    jobs = IndexJobs(catalog, annotator)
    if args.command == 'scan':
        catalog.add_root(args.folder)
        result = catalog.scan(VERSION)
    elif args.command == 'status':
        result = jobs.status()
    elif args.command == 'verify-model':
        identity = await annotator.verify()
        result = {key: identity.get(key) for key in ('name', 'digest', 'quantization', 'capabilities')}
    elif args.command == 'run':
        if not 1 <= args.max_photos <= 10000:
            parser.error('--max-photos deve essere tra 1 e 10000')
        await annotator.verify()
        for _ in range(args.max_photos):
            if not await jobs.one():
                break
        result = jobs.status()
    else:
        result = search(catalog, SearchPlan(terms=args.terms, folder=args.folder, place=args.place, since=args.since, until=args.until))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
