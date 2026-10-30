"""The songs of the music folder and of the folders inside it: listed with what their files say of themselves
(title, artist, album), and given as they are, to this PC's page and to a paired phone. Nothing here changes,
moves or deletes a song.

What a file says of itself is read here for the kinds most songs come in: MP3 (ID3), FLAC, Ogg and Opus (Vorbis
comments) and M4A (iTunes atoms). A file that says nothing is named after itself, and its folder is its album.
"""
import hashlib
import os
import re
import struct
import threading
import uuid
from pathlib import Path

# the kinds of song that both Android and the page of this PC play, and their names on the web
KINDS = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
}
# how much of a file is read for what it says of itself: the words come first, the pictures inside it after
HEAD = 64 * 1024
# the largest part of an M4A read for its words, the cover picture included
MOOV = 8 * 1024 * 1024
NAMES = {"title", "artist", "album"}
# where the songs a phone sends land, inside the music folder
FROM_THE_PHONE = "Dal telefono"


def safe_name(name: str) -> str:
    """A file name Windows takes, with nothing that could lead out of the folder: "a/b:c.mp3" is "b c.mp3"."""
    last = re.split(r"[\\/]", name)[-1]
    return re.sub(r'[:*?"<>|\x00-\x1f]', " ", last).strip().strip(".").strip()


def _syncsafe(four: bytes) -> int:
    """A size as ID3 writes it, seven bits a byte."""
    return (four[0] << 21) | (four[1] << 14) | (four[2] << 7) | four[3]


def _text(frame: bytes) -> str:
    """The words of an ID3 text frame: a byte that says how they are written, then the words."""
    if not frame:
        return ""
    written = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(frame[0], "latin-1")
    return frame[1:].decode(written, "replace").split("\x00")[0].strip()


def _id3(head: bytes) -> dict:
    """Title, artist and album from the ID3 tag at the start of an MP3 (versions 2.2, 2.3 and 2.4)."""
    if len(head) < 10 or head[:3] != b"ID3":
        return {}
    version, flags = head[3], head[5]
    tag = head[10:10 + _syncsafe(head[6:10])]
    at = 0
    if flags & 0x40 and version >= 3:
        # an extended header comes first, and says nothing of the song
        at = _syncsafe(tag[:4]) if version == 4 else struct.unpack(">I", tag[:4])[0] + 4
    names = {"TIT2": "title", "TPE1": "artist", "TALB": "album", "TT2": "title", "TP1": "artist", "TAL": "album"}
    width, header = (3, 6) if version == 2 else (4, 10)
    found: dict = {}
    while at + header <= len(tag):
        name = tag[at:at + width].decode("latin-1")
        if not name.strip("\x00"):
            break  # the padding after the last frame
        if version == 2:
            length = int.from_bytes(tag[at + 3:at + 6], "big")
        elif version == 4:
            length = _syncsafe(tag[at + 4:at + 8])
        else:
            length = struct.unpack(">I", tag[at + 4:at + 8])[0]
        if name in names and names[name] not in found:
            found[names[name]] = _text(tag[at + header:at + header + length])
        at += header + length
    return {key: value for key, value in found.items() if value}


def _id3v1(tail: bytes) -> dict:
    """Title, artist and album from the old ID3 tag, in the last 128 bytes of an MP3."""
    if len(tail) < 128 or tail[-128:-125] != b"TAG":
        return {}
    fields = tail[-125:]

    def field(start: int) -> str:
        return fields[start:start + 30].split(b"\x00")[0].decode("latin-1").strip()

    return {key: value for key, value in (("title", field(0)), ("artist", field(30)), ("album", field(60))) if value}


def _comments(block: bytes) -> dict:
    """Title, artist and album from Vorbis comments, as FLAC, Ogg and Opus write them: KEY=value, in UTF-8."""
    at = 4 + struct.unpack("<I", block[:4])[0]
    count = struct.unpack("<I", block[at:at + 4])[0]
    at += 4
    found: dict = {}
    for _ in range(count):
        length = struct.unpack("<I", block[at:at + 4])[0]
        key, _, value = block[at + 4:at + 4 + length].decode("utf-8", "replace").partition("=")
        at += 4 + length
        if key.lower() in NAMES and value.strip() and key.lower() not in found:
            found[key.lower()] = value.strip()
    return found


def _flac(head: bytes) -> dict:
    """The Vorbis comments among the blocks at the start of a FLAC."""
    if head[:4] != b"fLaC":
        return {}
    at = 4
    while at + 4 <= len(head):
        kind, length = head[at] & 0x7F, int.from_bytes(head[at + 1:at + 4], "big")
        if kind == 4:
            return _comments(head[at + 4:at + 4 + length])
        if head[at] & 0x80:
            break  # that was the last block
        at += 4 + length
    return {}


def _ogg(head: bytes) -> dict:
    """The Vorbis comments of an Ogg or Opus file, in its second packet."""
    for mark in (b"\x03vorbis", b"OpusTags"):
        at = head.find(mark)
        if at >= 0:
            return _comments(head[at + len(mark):])
    return {}


def _atoms(data: bytes, start: int, end: int):
    """The atoms of an MP4 between two places: (name, where its content starts, where it ends)."""
    at = start
    while at + 8 <= end:
        size, name = struct.unpack(">I4s", data[at:at + 8])
        header = 8
        if size == 1:
            size, header = struct.unpack(">Q", data[at + 8:at + 16])[0], 16
        elif size == 0:
            size = end - at
        if size < header:
            return
        yield name, at + header, min(at + size, end)
        at += size


def _ilst(moov: bytes) -> dict:
    """Title, artist and album from the list of an M4A's words: moov, udta, meta, ilst."""
    data = moov
    for wanted in (b"udta", b"meta", b"ilst"):
        inner = next(((start, end) for name, start, end in _atoms(data, 0, len(data)) if name == wanted), None)
        if inner is None:
            return {}
        # meta begins with a version and flags, before its atoms
        data = data[inner[0] + (4 if wanted == b"meta" else 0):inner[1]]
    names = {b"\xa9nam": "title", b"\xa9ART": "artist", b"\xa9alb": "album"}
    found: dict = {}
    for name, start, end in _atoms(data, 0, len(data)):
        if name not in names:
            continue
        for inner_name, inner_start, inner_end in _atoms(data, start, end):
            if inner_name == b"data":
                # after the kind of value and the language, the words
                found[names[name]] = data[inner_start + 8:inner_end].decode("utf-8", "replace").strip()
    return {key: value for key, value in found.items() if value}


def _m4a(file) -> dict:
    """The words of an M4A, which may come after the sound: the file is walked atom by atom, not read."""
    size = os.fstat(file.fileno()).st_size
    at = 0
    while at + 8 <= size:
        file.seek(at)
        length, name = struct.unpack(">I4s", file.read(8))
        header = 8
        if length == 1:
            length, header = struct.unpack(">Q", file.read(8))[0], 16
        elif length == 0:
            length = size - at
        if length < header:
            return {}
        if name == b"moov":
            return _ilst(file.read(min(length - header, MOOV)))
        at += length
    return {}


def tags(path: Path) -> dict:
    """What a song's file says of itself: title, artist and album, those it has."""
    kind = path.suffix.lower()
    try:
        with open(path, "rb") as file:
            if kind == ".m4a":
                return _m4a(file)
            head = file.read(HEAD)
            if kind == ".mp3":
                found = _id3(head)
                if not found:
                    file.seek(max(0, os.fstat(file.fileno()).st_size - 128))
                    found = _id3v1(file.read(128))
                return found
            if kind == ".flac":
                return _flac(head)
            if kind in (".ogg", ".oga", ".opus"):
                return _ogg(head)
    except (OSError, ValueError, IndexError, struct.error):
        pass  # a file that cannot be read says nothing: it is named after itself
    return {}


def _song(folder: Path, path: Path, size: int) -> dict:
    relative = path.relative_to(folder)
    said = tags(path)
    inside = relative.parent.as_posix() if relative.parent != Path(".") else ""
    # "01 - Volare.mp3" is "Volare": the number is the track's
    named = re.sub(r"^\d{1,3}\s*[-._)]?\s+", "", path.stem) or path.stem
    return {
        "id": hashlib.sha1(relative.as_posix().encode()).hexdigest()[:16],
        "name": path.name,
        "title": said.get("title") or named,
        "artist": said.get("artist", ""),
        "album": said.get("album") or (relative.parent.name if inside else ""),
        "folder": inside,
        "kind": path.suffix.lower().lstrip("."),
        "size": size,
    }


class Music:
    """The songs of a folder and of the folders inside it, at any depth."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self._lock = threading.Lock()
        # what was read of each file, as long as it stays the same: (size, time of the last change), song
        self._known: dict[str, tuple[tuple[int, int], dict]] = {}
        self._paths: dict[str, Path] = {}
        self._fingerprints: dict[Path, tuple[tuple[int, int], str]] = {}

    def songs(self) -> list[dict]:
        """All of them, by title. A file is read again only when it changed."""
        with self._lock:
            known, paths = {}, {}
            for path in self._files():
                try:
                    stat = path.stat()
                except OSError:
                    continue  # gone meanwhile
                key, stamp = path.relative_to(self.folder).as_posix(), (stat.st_size, stat.st_mtime_ns)
                before = self._known.get(key)
                song = before[1] if before and before[0] == stamp else _song(self.folder, path, stat.st_size)
                known[key], paths[song["id"]] = (stamp, song), path
            self._known, self._paths = known, paths
        return sorted((song for _, song in known.values()), key=lambda song: (song["title"].casefold(), song["artist"].casefold()))

    def path(self, identifier: str) -> Path | None:
        """The file of a song of the folder; None for anything else. A song added since the last list is found too."""
        if identifier not in self._paths:
            self.songs()
        return self._paths.get(identifier)

    def fingerprint(self, path: Path) -> str:
        """The SHA-256 of a song, which a phone checks the song against: worked out again only when the file changed."""
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns)
        kept = self._fingerprints.get(path)
        if kept and kept[0] == stamp:
            return kept[1]
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for part in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(part)
        self._fingerprints[path] = (stamp, digest.hexdigest())
        return digest.hexdigest()

    def incoming(self, name: str) -> Path:
        """Where a song a phone sends is written while it arrives: a hidden file in FROM_THE_PHONE, which is no song yet."""
        if Path(safe_name(name)).suffix.lower() not in KINDS:
            raise ValueError("not a song")
        folder = self.folder / FROM_THE_PHONE
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f".{uuid.uuid4().hex}.part"

    def land(self, partial: Path, name: str) -> str:
        """Gives a song that arrived whole its name, one that is free: "Volare (2).mp3" when "Volare.mp3" is there.
        Nothing already in the folder is written over. Says where it is, inside the music folder."""
        safe = Path(safe_name(name))
        target, number = partial.parent / safe.name, 2
        while True:
            try:
                if target.exists():
                    raise FileExistsError(target)
                partial.rename(target)
                return target.relative_to(self.folder).as_posix()
            except FileExistsError:
                target, number = partial.parent / f"{safe.stem} ({number}){safe.suffix}", number + 1

    def _files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return [path for path in self.folder.rglob("*") if path.suffix.lower() in KINDS and path.is_file()]
