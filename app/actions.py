"""What the app may do to the pictures, and how every change can be taken back.

No picture is ever deleted. "Delete" moves a picture into a trash folder inside the
picture folder itself, keeping where it came from; taking that back moves it home again.
A copy goes into a folder of its own. Every change is written in a journal, and a change
that was not taken back yet can be undone.

Nothing here decides anything: these functions are called only after the user has
confirmed, with pictures named by the index and never by a path that came from outside.
"""
import contextlib
import datetime
import json
import os
import re
import secrets
import shutil
import threading
from pathlib import Path

# the app's own folder inside the picture folder: the trash and the journal
HOME = ".regista"
# where copies go. It is not searched, or every copied picture would be found twice.
COLLECTIONS = "Raccolte"
# folders of the picture folder that are not part of the library
NOT_LIBRARY = {HOME, COLLECTIONS}


class Refused(Exception):
    """An action the app will not carry out. The message is for the user."""


def collection_name(text: str) -> str:
    """A folder name made from what the user wrote: no way out of the folder, nothing Windows refuses."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    name = re.sub(r"\s+", " ", name).strip(" .")[:60].strip(" .")
    if not name:
        raise Refused("Dimmi come chiamare la cartella.")
    return name


def free(path: Path) -> Path:
    """`path` if nothing is there, otherwise the same name with (2), (3)... Nothing is ever overwritten."""
    candidate, number = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        number += 1
    return candidate


class Actions:
    def __init__(self, root: str):
        self.root = Path(root)
        self.trash_dir = self.root / HOME / "cestino"
        self.journal = self.root / HOME / "registro.jsonl"
        # one change at a time: two at once could pick the same free name, or mix their lines in the journal
        self._lock = threading.Lock()

    # ---- helpers

    def _picture(self, relative: str) -> Path:
        """The file of a picture of the library. Anything that points elsewhere is refused."""
        path = (self.root / relative).resolve()
        inside = path.is_relative_to(self.root.resolve())
        if not inside or NOT_LIBRARY & set(Path(relative).parts):
            raise Refused(f"{relative} non è una foto della libreria.")
        return path

    def _move(self, source: Path, target: Path) -> Path:
        target = free(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # a rename: the file changes name and folder, its content is never copied or touched
        os.rename(source, target)
        return target

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _append(self, entry: dict) -> None:
        """Adds a line to the journal, and waits until it is really on the disk."""
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a+b") as journal:
            # a line cut short by a crash must not swallow this one: start on a line of its own
            size = journal.seek(0, os.SEEK_END)
            torn = size > 0 and (journal.seek(size - 1), journal.read(1))[1] != b"\n"
            journal.write((b"\n" if torn else b"") + json.dumps(entry).encode() + b"\n")
            journal.flush()
            os.fsync(journal.fileno())

    @staticmethod
    def _name() -> str:
        """A name for a change: when it was made, and a few letters so that two in the same second differ."""
        return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)

    def _tidy(self, folder: Path) -> None:
        """Removes a folder of the trash or of the collections that is now empty, and the empty ones above it. Never one with something in it."""
        while folder != self.root and self.root in folder.parents:
            try:
                folder.rmdir()  # refuses a folder that is not empty
            except OSError:
                return
            folder = folder.parent

    def _record(self, name: str, kind: str, files: list[dict], back, **more) -> dict:
        """Writes a change in the journal. A change that touched nothing leaves no line, and has no name."""
        entry = {
            "id": name if files else "",
            "kind": kind,
            # with the time zone, so that the page can show it as the user's clock does
            "when": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": files,
            **more,
        }
        if not files:
            return entry
        try:
            self._append(entry)
        except OSError:
            # a change that cannot be written down could not be taken back later: so it is taken back now
            for file in files:
                with contextlib.suppress(OSError):
                    back(file)
            raise
        return entry

    # ---- what the user can ask for

    def writable(self) -> bool:
        """Whether the picture folder can be changed at all: it may have been given to the app to read only."""
        return os.access(self.root, os.W_OK)

    def trash(self, relatives: list[str]) -> dict:
        """Moves pictures into the trash. They stay on the disk, and `undo` brings them back."""
        with self._lock:
            # every name is checked before anything is touched
            sources = [(relative, self._picture(relative)) for relative in relatives]
            # the folder in the trash has the name the change has in the journal: one can be found from the other
            name = self._name()
            batch = self.trash_dir / name
            files, missing, failed = [], 0, 0
            for relative, source in sources:
                if not source.is_file():
                    missing += 1
                    continue
                try:
                    # the same folders as in the library, so two pictures with the same name do not collide
                    kept = self._move(source, batch / relative)
                except OSError:
                    failed += 1  # open in another program, perhaps: it stays where it is and the others go ahead
                    continue
                files.append({"from": relative, "to": self._relative(kept)})
            entry = self._record(name, "trash", files, back=lambda file: self._move(self.root / file["to"], self.root / file["from"]))
            return {**entry, "count": len(files), "missing": missing, "failed": failed}

    def copy(self, relatives: list[str], folder: str) -> dict:
        """Copies pictures into a folder of the collections. The originals stay where they are."""
        with self._lock:
            target = self.root / COLLECTIONS / collection_name(folder)
            sources = [(relative, self._picture(relative)) for relative in relatives]
            files, missing, failed = [], 0, 0
            for relative, source in sources:
                if not source.is_file():
                    missing += 1
                    continue
                made = free(target / source.name)
                # written under another name first: a copy that stops halfway must never look like a picture
                partial = made.with_name(made.name + ".part")
                try:
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, partial)
                    os.rename(partial, made)
                except OSError:
                    failed += 1  # the disk is full, perhaps
                    with contextlib.suppress(OSError):
                        partial.unlink(missing_ok=True)
                    continue
                files.append({"from": relative, "to": self._relative(made)})
            # these are copies made a moment ago: taking them back loses nothing
            entry = self._record(self._name(), "copy", files, back=lambda file: (self.root / file["to"]).unlink(missing_ok=True), folder=target.name)
            return {**entry, "folder": target.name, "count": len(files), "missing": missing, "failed": failed}

    def albums(self, groups: list[tuple[str, list[str]]]) -> dict:
        """Copies pictures into several folders of the collections at once, one per album: one change, taken back as one.

        `groups` is (folder, pictures) for each album. The originals stay where they are.
        """
        with self._lock:
            # every name, of folder and of picture, is checked before anything is touched
            planned = [(self.root / COLLECTIONS / collection_name(folder), [(relative, self._picture(relative)) for relative in relatives]) for folder, relatives in groups]
            files, missing, failed, folders = [], 0, 0, []
            for target, sources in planned:
                made_here = 0
                for relative, source in sources:
                    if not source.is_file():
                        missing += 1
                        continue
                    made = free(target / source.name)
                    partial = made.with_name(made.name + ".part")
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, partial)
                        os.rename(partial, made)
                    except OSError:
                        failed += 1
                        with contextlib.suppress(OSError):
                            partial.unlink(missing_ok=True)
                        continue
                    files.append({"from": relative, "to": self._relative(made)})
                    made_here += 1
                if made_here:
                    folders.append(target.name)
            entry = self._record(self._name(), "albums", files, back=lambda file: (self.root / file["to"]).unlink(missing_ok=True), folder="", folders=folders)
            return {**entry, "folder": "", "folders": folders, "count": len(files), "missing": missing, "failed": failed}

    def incoming(self, folder: str) -> Path:
        """A temporary file in a folder of the collections, for a picture that is arriving from a phone."""
        directory = self.root / COLLECTIONS / collection_name(folder)
        directory.mkdir(parents=True, exist_ok=True)
        # under another name while it arrives: a picture that stops halfway must never look like one
        return directory / f"{secrets.token_hex(6)}.part"

    def land(self, partial: Path, name: str) -> str:
        """Gives a picture that has arrived its name, never the name of one already there. Returns where it is."""
        with self._lock:
            target = free(partial.parent / name)
            os.rename(partial, target)
            return self._relative(target)

    def arrived(self, files: list[dict], folder: str) -> dict:
        """Writes down the pictures that arrived from a phone, so that they can be taken back like any copy."""
        with self._lock:
            # if this cannot be written the pictures stay where they landed: they are copies, and the phone has the originals
            entry = self._record(self._name(), "receive", files, back=lambda file: None, folder=collection_name(folder))
            return {**entry, "count": len(files), "missing": 0, "failed": 0}

    def cleared(self, of: str, count: int) -> None:
        """Notes that pictures of an arrival were then taken off the phone they came from: the copies here are now the ones that stay."""
        with self._lock:
            self._append({"id": "", "kind": "cleared", "when": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "files": [], "of": of, "count": count})

    def history(self) -> list[dict]:
        """Every change made so far, oldest first, each with whether it was taken back, and how many of its pictures left their phone."""
        if not self.journal.exists():
            return []
        entries = []
        for line in self.journal.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue  # a line cut short by a crash does not make the others unreadable
        undone = {entry["of"] for entry in entries if entry["kind"] == "undo"}
        cleared = {entry["of"]: entry.get("count", 0) for entry in entries if entry["kind"] == "cleared"}
        return [{**entry, "undone": entry["id"] in undone, "cleared": cleared.get(entry["id"], 0)} for entry in entries if entry["kind"] != "cleared"]

    def last(self) -> dict | None:
        """The most recent change that can still be taken back."""
        return next((entry for entry in reversed(self.history()) if entry["kind"] != "undo" and not entry["undone"]), None)

    def undo(self, of: str = "") -> dict:
        """Takes back a change, the last one unless another is named.

        Pictures in the trash go home; copies leave their folder for the trash. If a file
        cannot be moved the change stays open, so that asking again finishes the job.
        """
        with self._lock:
            entry = next((one for one in self.history() if one["id"] == of and one["kind"] != "undo"), None) if of else self.last()
            if entry is None:
                raise Refused("Non c'è niente da annullare.")
            if entry["undone"]:
                raise Refused("Questa modifica è già stata annullata.")
            files, missing, failed = [], 0, 0
            for file in entry["files"]:
                where = self.root / file["to"]
                if not where.is_file():
                    missing += 1
                    continue
                try:
                    if entry["kind"] == "trash":
                        # home again; if something else took its place meanwhile, next to it under another name
                        moved = self._move(where, self.root / file["from"])
                    else:
                        # a copy that is no longer wanted is not deleted either: it goes to the trash
                        moved = self._move(where, self.trash_dir / f"annullate-{entry['id']}" / Path(file["to"]).name)
                except OSError:
                    failed += 1
                    continue
                files.append({"from": file["to"], "to": self._relative(moved)})
                # the folder it left is not kept if nothing is left in it
                self._tidy(where.parent)
            if not failed:
                self._append({"id": "", "kind": "undo", "when": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "files": files, "of": entry["id"]})
            return {"kind": "undo", "undid": entry["kind"], "of": entry["id"], "files": files, "count": len(files), "missing": missing, "failed": failed,
                    "folder": entry.get("folder", ""), "cleared": entry["cleared"]}

    def in_trash(self) -> int:
        """How many files are in the trash right now."""
        return sum(1 for path in self.trash_dir.rglob("*") if path.is_file()) if self.trash_dir.is_dir() else 0
