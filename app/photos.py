"""The pictures of a folder, searchable with a sentence.

Every picture is read once by a model that turns it into a list of numbers, its
"fingerprint". A sentence is turned into numbers by the same model, and the pictures
whose fingerprints are closest to the sentence are the ones that match it. The model
is given from outside (embedder.py), so that tests can run with a fake one.

Here the folder is only ever read: what changes it is in actions.py. The fingerprints
and the small copies for the page are kept somewhere else, in the index folder.
"""
import hashlib
import io
import json
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from actions import NOT_LIBRARY

KINDS = {".jpg", ".jpeg", ".png", ".webp"}
BATCH = 16
THUMB = 384
# How close a picture must be to a sentence to count as a match. Measured for the ViT-B/32
# model on 200 pictures of 10 kinds: pictures that showed the thing scored from 0.22 to 0.30,
# most of them 0.24 or more; the others were around 0.18, with a few as high as 0.26.
# So above SURE it is almost always a match, and between the two it is a "maybe".
SURE = 0.235
MAYBE = 0.215


def photo_id(relative: str) -> str:
    """A short name for a picture that does not give its path away and does not change between runs."""
    return hashlib.sha1(relative.encode()).hexdigest()[:12]


class PhotoIndex:
    def __init__(self, photos_dir: str, index_dir: str, embedder):
        self.photos_dir = Path(photos_dir)
        self.index_dir = Path(index_dir)
        self.embedder = embedder
        # one entry per indexed picture: {"id", "path" relative to the folder, "stamp"}
        self.photos: list[dict] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.state = {"running": False, "done": 0, "total": 0, "error": ""}
        self._lock = threading.Lock()
        # pictures and fingerprints change together: whoever reads or replaces them holds this
        self._swap = threading.Lock()
        self._load()

    # ---- on disk

    def _load(self) -> None:
        listing, vectors = self.index_dir / "photos.json", self.index_dir / "vectors.npy"
        if not (listing.exists() and vectors.exists()):
            return
        saved = json.loads(listing.read_text())
        # fingerprints made by another model cannot be compared with this one's: start again
        if isinstance(saved, dict) and saved.get("model") == self.embedder.name:
            self.photos = saved["photos"]
            self.vectors = np.load(vectors)

    def _save(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        np.save(self.index_dir / "vectors.npy", self.vectors)
        (self.index_dir / "photos.json").write_text(json.dumps({"model": self.embedder.name, "photos": self.photos}))

    def _files(self) -> list[Path]:
        if not self.photos_dir.is_dir():
            return []
        return sorted(
            path
            for path in self.photos_dir.rglob("*")
            if path.suffix.lower() in KINDS
            and path.is_file()
            # the trash and the copies are in the folder too, and are not part of the library
            and not NOT_LIBRARY & set(path.relative_to(self.photos_dir).parts)
        )

    # ---- building

    def build(self) -> None:
        """Reads the pictures that are new or changed, and forgets the ones that are gone.

        It is slow, a few pictures per second, and meant to run in a thread of its own:
        `state` says how far it is.
        """
        with self._lock:
            try:
                self._build()
            except Exception as exc:  # the page must learn that indexing stopped, and why
                self.state = {**self.state, "running": False, "error": f"{type(exc).__name__}: {exc}"}
                raise

    def _build(self) -> None:
        files = self._files()
        known = {photo["path"]: (photo, vector) for photo, vector in zip(self.photos, self.vectors)}
        kept, vectors, todo = [], [], []
        for file in files:
            relative = file.relative_to(self.photos_dir).as_posix()
            stat = file.stat()
            # a picture is the same as before if its size and its date are: no need to read it again
            stamp = f"{stat.st_size}-{int(stat.st_mtime)}"
            if relative in known and known[relative][0]["stamp"] == stamp:
                kept.append(known[relative][0])
                vectors.append(known[relative][1])
            else:
                todo.append((file, {"id": photo_id(relative), "path": relative, "stamp": stamp}))

        self.state = {"running": True, "done": len(kept), "total": len(files), "error": ""}
        for first in range(0, len(todo), BATCH):
            images, entries = [], []
            for file, entry in todo[first:first + BATCH]:
                try:
                    # a picture taken with the phone held upright is stored lying down, with a note: apply the note
                    images.append(ImageOps.exif_transpose(Image.open(file)).convert("RGB"))
                    entries.append(entry)
                except OSError:
                    continue  # a file that is not a readable picture is skipped, not fatal
            if images:
                vectors.extend(self.embedder.images(images))
                kept.extend(entries)
            # what is ready can be searched while the rest is still being read
            self._replace(kept, vectors)
            self.state = {**self.state, "done": len(kept)}

        self._replace(kept, vectors)
        self._save()
        self.state = {**self.state, "running": False, "done": len(kept)}

    def _replace(self, photos: list[dict], vectors: list) -> None:
        stacked = np.stack(vectors).astype(np.float32) if vectors else np.zeros((0, 0), dtype=np.float32)
        with self._swap:
            self.photos, self.vectors = list(photos), stacked

    # ---- searching

    def search(self, description: str, limit: int = 60) -> dict:
        """The pictures closest to a sentence, best first, split into sure matches and maybes.

        At most `limit` pictures come back; "matching" says how many sure matches there are in all.
        """
        with self._swap:
            photos, vectors = self.photos, self.vectors
        if not photos:
            return {"sure": [], "maybe": [], "matching": 0, "indexed": 0}
        # rounded once, so that what is counted and what is shown agree on which side of a threshold a picture is
        scores = np.round((vectors @ self.embedder.text(description)).astype(np.float64), 3)
        order = np.argsort(-scores, kind="stable")[:limit]
        found = [{"id": photos[i]["id"], "name": Path(photos[i]["path"]).name, "score": float(scores[i])} for i in order]
        return {
            "sure": [photo for photo in found if photo["score"] >= SURE],
            "maybe": [photo for photo in found if MAYBE <= photo["score"] < SURE],
            "matching": int((scores >= SURE).sum()),
            "indexed": len(photos),
        }

    def forget(self, identifiers: list[str]) -> None:
        """Drops pictures from the index at once, without waiting for the folder to be read again."""
        gone = set(identifiers)
        with self._swap:
            keep = [position for position, photo in enumerate(self.photos) if photo["id"] not in gone]
            self.photos = [self.photos[position] for position in keep]
            self.vectors = self.vectors[keep] if keep else np.zeros((0, 0), dtype=np.float32)

    # ---- showing

    def _known(self, identifier: str) -> dict | None:
        return next((photo for photo in self.photos if photo["id"] == identifier), None)

    def relative_of(self, identifier: str) -> str | None:
        """Where a picture is inside the folder, found by its short name. A path never comes from outside."""
        photo = self._known(identifier)
        return photo["path"] if photo else None

    def path_of(self, identifier: str) -> Path | None:
        relative = self.relative_of(identifier)
        return self.photos_dir / relative if relative else None

    def thumbnail(self, identifier: str) -> bytes | None:
        """A small copy of a picture for the page, made the first time it is asked for and then kept."""
        photo = self._known(identifier)
        if photo is None:
            return None
        # kept under the size and date of the picture: if another file takes its name, the old
        # small copy is not shown for it. What is on screen is what an action would touch.
        cached = self.index_dir / "thumbs" / f"{identifier}-{photo['stamp']}.jpg"
        if cached.exists():
            return cached.read_bytes()
        path = self.photos_dir / photo["path"]
        if not path.exists():
            return None
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        image.thumbnail((THUMB, THUMB))
        data = io.BytesIO()
        image.save(data, "JPEG", quality=82)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data.getvalue())
        return data.getvalue()
