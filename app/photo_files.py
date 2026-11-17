"""Publish managed files without ever replacing a concurrently-created destination."""
import errno
import hashlib
import os
from pathlib import Path
import shutil

RENAME_REFUSES_REPLACEMENT = os.name == 'nt'


def move_new(source: Path, destination: Path, expected_sha: str | None = None):
    renamed = False
    try:
        os.link(source, destination)
    except FileExistsError:
        raise
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES, errno.EXDEV, errno.ENOTSUP, errno.ENOSYS):
            raise
        if RENAME_REFUSES_REPLACEMENT:
            # Windows rename refuses an existing destination, including on filesystems without links.
            source.rename(destination)
            renamed = True
        # Some mounted photo volumes do not implement hard links. Retain the source until a complete,
        # flushed exclusive copy exists. A partial destination after an I/O failure remains recoverable.
        else:
            with destination.open('xb') as target, source.open('rb') as original:
                shutil.copyfileobj(original, target)
                target.flush()
                os.fsync(target.fileno())
    if expected_sha:
        digest = hashlib.sha256()
        with destination.open('rb') as landed:
            for chunk in iter(lambda: landed.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha:
            raise ValueError('Copia modificata durante lo spostamento; originale conservato.')
    if not renamed:
        source.unlink()
