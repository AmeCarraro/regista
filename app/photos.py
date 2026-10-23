"""The pictures of a folder, searchable with a sentence.

Every picture is read once by a model that turns it into a list of numbers, its
"fingerprint". A sentence is turned into numbers by the same model, and the pictures
whose fingerprints are closest to the sentence are the ones that match it. The model
is given from outside (embedder.py), so that tests can run with a fake one.

Here the folder is only ever read: what changes it is in actions.py. The fingerprints
and the small copies for the page are kept somewhere else, in the index folder.
"""
import datetime
import hashlib
import io
import json
import re
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from actions import NOT_LIBRARY
from places import position_of
from trips import trips

KINDS = {".jpg", ".jpeg", ".png", ".webp"}
BATCH = 16
THUMB = 384
# the fewest pixels a picture is read with for the model, on its shorter side: twice the 224 it sees (embedder.py)
READ = 448
# How close a picture must be to a sentence to count as a match: the same as on the phone. Measured
# with the small models (embedder.py) on the 200 sample pictures and 20 captions as the director
# writes them: from 0.26, 94% of the pictures shown are right and 77% of the right ones are shown;
# from 0.24, 77% and 92%. So above SURE it is almost always a match, and between the two a "maybe".
SURE = 0.26
MAYBE = 0.24
# Two pictures are copies of one another when the model finds them this alike AND their look in pixels
# (look_of: 64 bits) is this close. Measured on the 200 sample pictures and on changed copies of them:
# a copy saved again, made smaller, brighter or black and white was 0 to 5 bits away and at least
# 0.73 alike (made very small), 0.89 or more otherwise; a copy cut 5% at the edges 4 to 15 bits away.
# Two different pictures were at least 14 bits apart, and up to 0.95 alike (two golf balls on grass):
# what the model sees alone takes them for copies, the bits alone do not know what is shown.
TWIN_ALIKE = 0.85
TWIN_BITS = 10
# Screenshots of the same app look alike in pixels and in what they show, whatever their words say:
# on the tablet, four of a chat taken minutes apart were found "copies". They are never taken for copies.
SCREENSHOT = re.compile(r"^(?:screenshot|schermata|screen[ _-]?shot)", re.IGNORECASE)
# a day written in a name: 20230812, 2023-08-12, 2023_08_12, with no other figure stuck to it
NAMED_DAY = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")
# what is noted of each picture: a picture noted by an older version is noted again, from its file
NOTES = 2
# The pictures looked at one by one after the first search, by a model that sees (orchestrator.py):
# the likeliest first, by the words and by what the sure ones look like together, and no more than
# LOOK_MOST; the looking stops after LOOK_STOP wrong in a row. Measured on the 200 samples with the
# eyes taken as always right: 33 looks per search found 98% of the right pictures. LOOK_MOST is there
# for a large library, where a common subject can be in hundreds: about seven minutes of looking.
LOOK_SHIFT = 0.35
LOOK_MOST = 500
LOOK_STOP = 10


def photo_id(relative: str) -> str:
    """A short name for a picture that does not give its path away and does not change between runs."""
    return hashlib.sha1(relative.encode()).hexdigest()[:12]


def look_of(picture: Image.Image) -> str:
    """How a picture looks in pixels, in 64 bits as 16 hex figures: whether each of 8×9 grey squares is brighter than the one on its left.

    It stays the same for a copy saved again, made smaller or brighter, and is far from it for another picture.
    """
    small = np.asarray(picture.convert("L").resize((9, 8), Image.LANCZOS), dtype=np.int16)
    return np.packbits(small[:, 1:] > small[:, :-1]).tobytes().hex()


def opened(file: Path, side: int) -> Image.Image:
    """A picture upright and in colour, with at least `side` pixels each way if it has them. A JPEG is reduced
    while it is decoded, by a half, a quarter or an eighth: many times faster than reading it whole."""
    image = Image.open(file)
    image.draft("RGB", (side, side))
    return ImageOps.exif_transpose(image).convert("RGB")


def looked(file: Path) -> dict:
    """The look of a picture file, and how many pixels it has. Fast: from the reduced copy a JPEG gives without being read whole."""
    with Image.open(file) as image:
        pixels = image.width * image.height
        image.draft("RGB", (64, 64))
        return {"look": look_of(ImageOps.exif_transpose(image)), "pixels": pixels}


def _worth(entry: dict) -> tuple:
    """Which of two copies is kept, the first in this order: more pixels, a larger file, taken earlier, a shorter name."""
    try:
        # on this computer the stamp starts with the size of the file
        size = int(str(entry.get("stamp", "")).split("-")[0]) if "path" in entry else 0
    except ValueError:
        size = 0
    return (-entry.get("pixels", 0), -size, entry.get("day") or "9999", len(entry["name"]), entry["name"])


def twins(entries: list[dict], vectors: np.ndarray, period: tuple | None = None) -> list[list[int]]:
    """Groups of pictures that are copies of one another, as positions in `entries`, the one to keep first.

    Each entry has its "look" and "name"; a picture with no look is left out. With a `period`, only the
    groups with a picture taken in it: a copy received in a chat later has the day it arrived.
    """
    inside = [position for position, entry in enumerate(entries) if entry.get("look") and not SCREENSHOT.match(entry["name"])]
    if len(inside) < 2:
        return []
    alike = vectors[inside]
    bits = np.unpackbits(np.frombuffer(bytes.fromhex("".join(entries[position]["look"] for position in inside)), dtype=np.uint8).reshape(len(inside), 8), axis=1)
    parent = list(range(len(inside)))

    def root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    # by blocks of rows: the whole table of how alike every two pictures are would not fit in memory
    for start in range(0, len(inside), 512):
        rows, columns = np.nonzero(alike[start:start + 512] @ alike.T >= TWIN_ALIKE)
        rows = rows + start
        pairs = rows < columns
        rows, columns = rows[pairs], columns[pairs]
        close = np.count_nonzero(bits[rows] != bits[columns], axis=1) <= TWIN_BITS
        for one, other in zip(rows[close], columns[close]):
            parent[root(int(one))] = root(int(other))
    groups: dict[int, list[int]] = {}
    for at in range(len(inside)):
        groups.setdefault(root(at), []).append(inside[at])
    found = [sorted(members, key=lambda position: _worth(entries[position])) for members in groups.values() if len(members) > 1]
    if period:
        since, until = period[0].isoformat(), period[1].isoformat()
        found = [group for group in found if any(since <= entries[position].get("day", "") <= until for position in group)]
    return found


def day_in_name(name: str) -> str:
    """The day a name says a picture was taken: "IMG_20230812_142530.jpg", "IMG-20230812-WA0003.jpg",
    "WhatsApp Image 2023-08-12 at 14.25.30.jpeg", "Screenshot_20230702-104906.png". Empty when it says none."""
    for found in NAMED_DAY.finditer(name):
        try:
            day = datetime.date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
        except ValueError:
            continue
        if datetime.date(1990, 1, 1) <= day <= datetime.date.today() + datetime.timedelta(days=1):
            return day.isoformat()
    return ""


def day_of(file: Path) -> str:
    """The day a picture was taken, as "2024-08-15": the one the camera wrote in it; else the one in its name,
    which a picture received in a chat keeps when the camera's note is gone; else the date of the file."""
    try:
        with Image.open(file) as image:
            written = image.getexif()
            # the day it was taken is the camera's own note; the day it was changed stands in for pictures that only have that
            when = written.get_ifd(0x8769).get(0x9003) or written.get(0x0132)
        if when:
            return datetime.datetime.strptime(str(when)[:10], "%Y:%m:%d").date().isoformat()
    except (OSError, ValueError):
        pass
    return day_in_name(file.name) or datetime.date.fromtimestamp(file.stat().st_mtime).isoformat()


def closest(vectors: np.ndarray, sentence: np.ndarray | None, entries: list[dict], limit: int, period: tuple | None = None, only: list[int] | None = None) -> dict:
    """The pictures closest to a sentence, best first, split into sure matches and maybes.

    `entries` are the pictures, each with "id", "name" and "day", in the order of their
    fingerprints. With a `period` (first day, last day) only the pictures taken then are
    looked at, and with `only` just the ones at those positions of the list (the ones taken
    in a place). Without a sentence, all of them match, the newest first. At most `limit`
    come back; "matching" says how many sure matches there are in all.
    """
    known = len(entries)
    if period or only is not None:
        inside = list(range(known)) if only is None else only
        if period:
            since, until = period[0].isoformat(), period[1].isoformat()
            inside = [position for position in inside if since <= entries[position].get("day", "") <= until]
        entries = [entries[position] for position in inside]
        vectors = vectors[inside] if inside else vectors[:0]
    if not entries:
        return {"sure": [], "maybe": [], "matching": 0, "indexed": known}
    if sentence is None:
        newest = sorted(entries, key=_newest)[:limit]
        return {"sure": [{"id": entry["id"], "name": entry["name"], "day": entry.get("day", ""), "score": 1.0} for entry in newest], "maybe": [], "matching": len(entries), "indexed": known}
    # rounded once, so that what is counted and what is shown agree on which side of a threshold a picture is
    scores = np.round((vectors @ sentence).astype(np.float64), 3)
    order = np.argsort(-scores, kind="stable")[:limit]
    found = [{"id": entries[i]["id"], "name": entries[i]["name"], "day": entries[i].get("day", ""), "score": float(scores[i])} for i in order]
    # the closest are chosen; they are shown the newest first, as a gallery does
    return {
        "sure": sorted((photo for photo in found if photo["score"] >= SURE), key=_newest),
        "maybe": sorted((photo for photo in found if MAYBE <= photo["score"] < SURE), key=_newest),
        "matching": int((scores >= SURE).sum()),
        "indexed": known,
    }


def _newest(entry: dict) -> tuple:
    """The newest first; on the same day, by name; a picture with no day at the end."""
    day = entry.get("day", "")
    return (not day, tuple(-ord(char) for char in day), entry.get("name", ""))


def to_look_at(vectors: np.ndarray, sentence: np.ndarray, entries: list[dict], period: tuple | None = None, only: list[int] | None = None,
               most: int = LOOK_MOST) -> list[dict]:
    """The pictures worth looking at one by one for a sentence, the likeliest first: {"id", "name", "day", "score"}.

    Likeliest by the words, and by the words together with what the sure ones look like: a picture
    the words alone rank low is found through the ones that show it plainly. With a `period` and with
    `only`, as in closest().
    """
    if period or only is not None:
        inside = list(range(len(entries))) if only is None else only
        if period:
            since, until = period[0].isoformat(), period[1].isoformat()
            inside = [position for position in inside if since <= entries[position].get("day", "") <= until]
        entries = [entries[position] for position in inside]
        vectors = vectors[inside] if inside else vectors[:0]
    if not entries:
        return []
    words = vectors @ sentence
    key = words
    sure = words >= SURE
    if sure.any():
        mean = vectors[sure].mean(axis=0)
        both = sentence + mean / np.linalg.norm(mean)
        key = np.maximum(words, vectors @ (both / np.linalg.norm(both)) - LOOK_SHIFT)
    return [{"id": entries[i]["id"], "name": entries[i]["name"], "day": entries[i].get("day", ""), "score": round(float(words[i]), 3)}
            for i in np.argsort(-key, kind="stable")[:most]]


class PhotoIndex:
    def __init__(self, photos_dir: str, index_dir: str, embedder, places=None):
        self.photos_dir = Path(photos_dir)
        self.index_dir = Path(index_dir)
        self.embedder = embedder
        # the table that turns a position into a country (places.py); without it pictures are not found by place
        self.places = places
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

    def _noted(self, file: Path) -> dict:
        """What is written in a picture about itself: the day it was taken, and where, if its camera knew."""
        position = position_of(file)
        country, region = self.places.where(position) if self.places else ("", "")
        try:
            seen = looked(file)
        except (OSError, ValueError, Image.DecompressionBombError):
            seen = {"look": "", "pixels": 0}  # not a picture that can be read: it has no look, and is nobody's copy
        return {
            "day": day_of(file),
            "lat": position[0] if position else None,
            "lon": position[1] if position else None,
            "country": country,
            "region": region,
            **seen,
            "notes": NOTES,
        }

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
                # a picture read before days and places were kept gets them now: they are written in the file,
                # and the picture itself is not read again
                noted = known[relative][0].get("notes") == NOTES and all(key in known[relative][0] for key in ("day", "lat", "region", "look"))
                kept.append(known[relative][0] if noted else {**known[relative][0], **self._noted(file)})
                vectors.append(known[relative][1])
            else:
                todo.append((file, {"id": photo_id(relative), "path": relative, "stamp": stamp, **self._noted(file)}))

        self.state = {"running": True, "done": len(kept), "total": len(files), "error": ""}
        for first in range(0, len(todo), BATCH):
            images, entries = [], []
            for file, entry in todo[first:first + BATCH]:
                try:
                    # a picture taken with the phone held upright is stored lying down, with a note: apply the note
                    images.append(opened(file, READ))
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

    def search(self, description: str, limit: int = 60, period: tuple | None = None, spot: dict | None = None) -> dict:
        """The pictures closest to a sentence, best first, split into sure matches and maybes.

        With a `period` only the pictures taken in it, with a `spot` only the ones taken
        there; with no description, all of those. At most `limit` pictures come back;
        "matching" says how many sure matches there are in all.
        """
        with self._swap:
            photos, vectors = self.photos, self.vectors
        if not photos:
            return closest(vectors, None, [], limit)
        entries = [{**photo, "name": Path(photo["path"]).name} for photo in photos]
        only = self.places.inside(spot, entries) if spot and self.places else None
        return closest(vectors, self.embedder.text(description) if description else None, entries, limit, period, only)

    def to_look_at(self, description: str, period: tuple | None = None, spot: dict | None = None) -> list[dict]:
        """The pictures worth looking at one by one for a description, the likeliest first (to_look_at)."""
        with self._swap:
            photos, vectors = self.photos, self.vectors
        if not photos:
            return []
        entries = [{**photo, "name": Path(photo["path"]).name} for photo in photos]
        only = self.places.inside(spot, entries) if spot and self.places else None
        return to_look_at(vectors, self.embedder.text(description), entries, period, only)

    def twins(self, period: tuple | None = None) -> list[list[dict]]:
        """The pictures that are copies of one another, in groups, the one to keep first: each {"id", "name", "day"}."""
        with self._swap:
            photos, vectors = self.photos, self.vectors
        entries = [{**photo, "name": Path(photo["path"]).name} for photo in photos]
        return [[{key: entries[position].get(key, "") for key in ("id", "name", "day")} for position in group] for group in twins(entries, vectors, period)]

    def trips(self) -> list[dict]:
        """The trips the pictures tell of, the latest first (trips.py)."""
        with self._swap:
            photos = self.photos
        return trips([{**photo, "name": Path(photo["path"]).name} for photo in photos], self.places)

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
        image = opened(path, THUMB)
        image.thumbnail((THUMB, THUMB))
        data = io.BytesIO()
        image.save(data, "JPEG", quality=82)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data.getvalue())
        return data.getvalue()
