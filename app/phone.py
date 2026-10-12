"""The phones that may talk to this computer, and what the computer knows of their pictures.

A phone is let in once, with a link that only this computer knows and shows as a QR code:
from then on the phone proves who it is with a key of its own. What a phone sends is a
small copy of each of its pictures. The computer reads them as it reads its own, so they
can be searched here; the pictures themselves stay on the phone until the user asks for
some. Then the computer asks, and the phone sends the originals.

Everything travels encrypted, with a certificate this computer makes for itself. Its
fingerprint is in the link, so the phone talks only to the computer it was shown.
"""
import base64
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
from PIL import Image, ImageOps

from actions import Refused
from photos import BATCH, THUMB, closest

# how long the link that lets a phone in stays good
INVITE_SECONDS = 300
# the largest small copy a phone may send, as text: a 384-pixel JPEG is a tenth of this
SMALL_COPY = 600_000
# and the most pixels it may have: a phone of ours sends 384 on the long side
SMALL_COPY_PIXELS = 1600 * 1600
# what a file that arrives from a phone may end in
ENDINGS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "gif", "avif", "dng"}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def phone_photo_id(device: str, media: str) -> str:
    """The short name of a picture of a phone. It starts with a letter that no picture of this computer starts with."""
    return "t" + hashlib.sha1(f"{device}:{media}".encode()).hexdigest()[:12]


def on_phone(identifier: str) -> bool:
    """Whether a short name is of a picture that is on a phone."""
    return identifier.startswith("t")


def file_name(text: str) -> str:
    """A file name for a picture that arrives from a phone: a name and nothing else, ending as a picture does."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    name = re.sub(r"\s+", " ", name).strip(" .")[:120].strip(" .")
    ending = name.rpartition(".")[2].lower() if "." in name else ""
    return name if ending in ENDINGS else f"{name or 'foto'}.jpg"


class Phones:
    def __init__(self, folder: str, embedder, addresses: list[str], port: int, computer: str = "", places=None):
        self.folder = Path(folder)
        self.embedder = embedder
        # the table that turns a position into a country (places.py)
        self.places = places
        # where a phone finds this computer, as whoever started the app saw it from outside
        self.addresses, self.port, self.computer = addresses, port, computer
        self._lock = threading.RLock()
        # the secret of the link on show, and when it stops being good
        self._invite: tuple[str, float] | None = None
        self._saved = 0.0
        self.devices: list[dict] = self._read("devices.json", [])
        # the pictures of every phone: {"id", "device", "media" (the phone's own name for it), "stamp", "name", "day"}
        self.photos: list[dict] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.transfers: list[dict] = self._read("transfers.json", [])
        listing, vectors = self.folder / "photos.json", self.folder / "vectors.npy"
        if listing.exists() and vectors.exists():
            saved = json.loads(listing.read_text())
            # fingerprints made by another model cannot be compared with this one's: the phones will send again
            if saved.get("model") == self.embedder.name:
                self.photos, self.vectors = saved["photos"], np.load(vectors)

    # ---- on disk

    def _read(self, name: str, default):
        file = self.folder / name
        return json.loads(file.read_text()) if file.exists() else default

    def _write(self, name: str, value) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        partial = self.folder / f"{name}.part"
        partial.write_text(json.dumps(value))
        os.replace(partial, self.folder / name)

    def save(self) -> None:
        """Writes down what is known of the phones' pictures."""
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            np.save(self.folder / "vectors.npy", self.vectors)
            self._write("photos.json", {"model": self.embedder.name, "photos": self.photos})
            self._saved = time.monotonic()

    # ---- the certificate

    def certificate(self) -> tuple[Path, Path]:
        """The certificate this computer shows to the phones, and its key. Made the first time, then kept."""
        certificate, key = self.folder / "certificate.pem", self.folder / "key.pem"
        with self._lock:
            if not (certificate.exists() and key.exists()):
                self.folder.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                     "-keyout", str(key), "-out", str(certificate), "-days", "3650", "-subj", "/CN=regista"],
                    check=True, capture_output=True,
                )
        return certificate, key

    def fingerprint(self) -> str:
        """What tells this computer's certificate from any other. The phone gets it in the link, and accepts no other."""
        text = self.certificate()[0].read_text()
        body = text.split("-----BEGIN CERTIFICATE-----")[1].split("-----END CERTIFICATE-----")[0]
        return hashlib.sha256(base64.b64decode(body)).hexdigest()

    # ---- letting a phone in

    def invite(self) -> dict:
        """A new link that lets one phone in, once, for a few minutes. It replaces the one before."""
        secret = secrets.token_urlsafe(18)
        with self._lock:
            self._invite = (secret, time.monotonic() + INVITE_SECONDS)
        query = urlencode({"a": ",".join(self.addresses), "p": self.port, "s": secret, "f": self.fingerprint(), "n": self.computer})
        return {"link": f"regista://pair?{query}", "seconds": INVITE_SECONDS}

    def pair(self, secret: str, name: str) -> dict:
        """Lets in the phone that shows the secret of the link. It gets a key of its own, which is told only now."""
        with self._lock:
            invite = self._invite
            if invite is None or time.monotonic() > invite[1] or not secrets.compare_digest(secret.encode(), invite[0].encode()):
                raise Refused("Questo collegamento non vale più: fanne uno nuovo dal computer.")
            self._invite = None
            token = secrets.token_urlsafe(32)
            device = {
                "id": secrets.token_hex(4),
                "name": re.sub(r"[\x00-\x1f]", " ", name).strip()[:40] or "Telefono",
                # the key itself is not kept: only what proves that a key is the right one
                "key": hashlib.sha256(token.encode()).hexdigest(),
                "paired": _now(),
                "seen": _now(),
            }
            self.devices.append(device)
            self._write("devices.json", self.devices)
            return {"token": token, "device": device["id"], "computer": self.computer}

    def device_of(self, token: str) -> dict | None:
        """The phone a key belongs to, if it is the key of a phone that was let in."""
        key = hashlib.sha256(token.encode()).hexdigest()
        device = next((device for device in self.devices if secrets.compare_digest(device["key"], key)), None)
        if device:
            device["seen"] = _now()
        return device

    def forget_device(self, device: str) -> bool:
        """Shuts a phone out: its key stops working, and what was known of its pictures is dropped."""
        with self._lock:
            if not any(known["id"] == device for known in self.devices):
                return False
            self.devices = [known for known in self.devices if known["id"] != device]
            self._drop({photo["id"] for photo in self.photos if photo["device"] == device})
            for transfer in self.transfers:
                if transfer["device"] == device and transfer["state"] == "waiting":
                    transfer["state"] = "done"
            self._write("devices.json", self.devices)
            self._write("transfers.json", self.transfers)
            self.save()
            return True

    def described(self) -> list[dict]:
        """The phones that were let in, as the page shows them. Never their keys."""
        with self._lock:
            return [
                {
                    "id": device["id"],
                    "name": device["name"],
                    "paired": device["paired"],
                    "seen": device["seen"],
                    "photos": sum(1 for photo in self.photos if photo["device"] == device["id"]),
                    "waiting": sum(len(self._left(transfer)) for transfer in self.transfers if transfer["device"] == device["id"] and transfer["state"] == "waiting"),
                }
                for device in self.devices
            ]

    # ---- what is known of the pictures of a phone

    def _drop(self, gone: set[str]) -> None:
        keep = [position for position, photo in enumerate(self.photos) if photo["id"] not in gone]
        for identifier in gone:
            # a small copy of a picture that is no longer on the phone is of no use here
            (self.folder / "thumbs" / f"{identifier}.jpg").unlink(missing_ok=True)
        self.photos = [self.photos[position] for position in keep]
        self.vectors = self.vectors[keep] if keep else np.zeros((0, 0), dtype=np.float32)

    def wanted(self, device: str, listing: list[dict]) -> list[str]:
        """Which pictures of a phone this computer still needs a small copy of.

        `listing` is every picture the phone has, each with its "id" and a "stamp" that
        changes when the picture does. Pictures it no longer lists are forgotten here.
        """
        with self._lock:
            there = {str(item["id"]): str(item.get("stamp", "")) for item in listing}
            mine = [photo for photo in self.photos if photo["device"] == device]
            gone = {photo["id"] for photo in mine if photo["media"] not in there}
            if gone:
                self._drop(gone)
                self.save()
            # a picture sent by an app that did not say yet its day, or where it was taken, is asked for again
            known = {photo["media"]: photo["stamp"] for photo in mine if photo.get("day") and "lat" in photo}
            return [media for media, stamp in there.items() if known.get(media) != stamp]

    def add(self, device: str, arrived: list[dict]) -> int:
        """Takes small copies of pictures from a phone, reads them as this computer reads its own, and keeps them to show."""
        pictures, entries = [], []
        for item in arrived[:BATCH]:
            try:
                data = str(item["jpeg"])
                if len(data) > SMALL_COPY:
                    continue
                picture = Image.open(io.BytesIO(base64.b64decode(data)))
                # a few bytes can claim to be an enormous picture, and opening it would fill the memory:
                # a small copy is small, so anything else is refused before it is opened
                if picture.width * picture.height > SMALL_COPY_PIXELS:
                    continue
                picture = ImageOps.exif_transpose(picture).convert("RGB")
            except (OSError, ValueError, KeyError):
                continue  # one that cannot be read is skipped: the phone will offer it again
            picture.thumbnail((THUMB, THUMB))
            media = str(item["id"])
            day = str(item.get("day", ""))
            position = self._position(item)
            entries.append({
                "id": phone_photo_id(device, media),
                "device": device,
                "media": media,
                "stamp": str(item.get("stamp", "")),
                "name": file_name(str(item.get("name", ""))),
                # the day it was taken, as the clock and the calendar of the phone say it
                "day": day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else "",
                # where it was taken, if the phone knew and was allowed to say
                "lat": position[0] if position else None,
                "lon": position[1] if position else None,
                "country": self.places.of(position) if self.places else "",
            })
            pictures.append(picture)
        if not pictures:
            return 0
        vectors = np.asarray(self.embedder.images(pictures), dtype=np.float32)
        with self._lock:
            (self.folder / "thumbs").mkdir(parents=True, exist_ok=True)
            for entry, picture in zip(entries, pictures):
                # written again here as a JPEG of this computer's: the page never shows bytes as a phone sent them
                picture.save(self.folder / "thumbs" / f"{entry['id']}.jpg", "JPEG", quality=82)
            fresh = {entry["id"] for entry in entries}
            keep = [position for position, photo in enumerate(self.photos) if photo["id"] not in fresh]
            self.photos = [self.photos[position] for position in keep] + entries
            self.vectors = np.concatenate([self.vectors[keep], vectors]) if keep else vectors
            # a phone sends thousands of these in a row: writing everything down each time would take longer than reading them
            if time.monotonic() - self._saved > 20:
                self.save()
        return len(entries)

    @staticmethod
    def _position(item: dict) -> tuple[float, float] | None:
        """Where a phone says a picture was taken, if what it says is a place on Earth."""
        try:
            latitude, longitude = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        inside = -90 <= latitude <= 90 and -180 <= longitude <= 180 and (latitude, longitude) != (0, 0)
        return (round(latitude, 5), round(longitude, 5)) if inside else None

    def search(self, description: str, limit: int = 60, period: tuple | None = None, spot: dict | None = None) -> dict:
        """The pictures of the phones closest to a sentence: the same answer the pictures of this computer give."""
        with self._lock:
            photos, vectors = self.photos, self.vectors
        if not photos:
            return closest(vectors, None, [], limit)
        only = self.places.inside(spot, photos) if spot and self.places else None
        return closest(vectors, self.embedder.text(description) if description else None, photos, limit, period, only)

    def thumbnail(self, identifier: str) -> bytes | None:
        file = self.folder / "thumbs" / f"{identifier}.jpg"
        known = any(photo["id"] == identifier for photo in self.photos)
        return file.read_bytes() if known and file.exists() else None

    # ---- asking a phone for the originals

    def _left(self, transfer: dict) -> list[str]:
        known = {photo["id"] for photo in self.photos}
        # a picture the phone no longer has cannot arrive: it is not waited for
        return [identifier for identifier in transfer["photos"] if identifier in known and identifier not in transfer["arrived"] and identifier not in transfer["missing"]]

    def ask(self, identifiers: list[str], folder: str) -> dict:
        """Asks a phone for the originals of some of its pictures, to go into a folder of the collections.

        Nothing arrives now: the phone answers when its app is open. One phone at a time.
        """
        with self._lock:
            known = {photo["id"]: photo for photo in self.photos}
            chosen = [known[identifier] for identifier in dict.fromkeys(identifiers) if identifier in known]
            if not chosen:
                raise Refused("Quelle foto del telefono non le conosco più.")
            device = chosen[0]["device"]
            transfer = {
                "id": secrets.token_hex(6),
                "device": device,
                "folder": folder,
                "photos": [photo["id"] for photo in chosen if photo["device"] == device],
                # short name of the picture -> where it is now, inside the picture folder
                "arrived": {},
                "missing": [],
                "state": "waiting",
                "asked": _now(),
                # the name of the change in the journal, once everything has arrived
                "entry": "",
            }
            self.transfers.append(transfer)
            self._write("transfers.json", self.transfers)
            return transfer

    def transfer(self, identifier: str) -> dict | None:
        return next((transfer for transfer in self.transfers if transfer["id"] == identifier), None)

    def work(self, device: str) -> list[dict]:
        """What a phone is asked to send: for every request still open, the pictures that have not arrived yet."""
        with self._lock:
            media = {photo["id"]: photo["media"] for photo in self.photos}
            return [
                {"id": transfer["id"], "photos": [{"id": identifier, "media": media[identifier]} for identifier in self._left(transfer)]}
                for transfer in self.transfers
                if transfer["device"] == device and transfer["state"] == "waiting"
            ]

    def expected(self, transfer: str, device: str, identifier: str) -> dict:
        """The picture a phone is about to send, if it was asked for and has not arrived yet. Anything else is refused."""
        with self._lock:
            found = self.transfer(transfer)
            if found is None or found["device"] != device or found["state"] != "waiting" or identifier not in self._left(found):
                raise Refused("Questa foto non è stata chiesta.")
            return {"folder": found["folder"], "name": next(photo["name"] for photo in self.photos if photo["id"] == identifier)}

    def settle(self, transfer: str, device: str, arrived: dict | None = None, missing: list[str] | None = None) -> dict | None:
        """Notes pictures that arrived, or that the phone could not send. Returns the request if this was its last picture."""
        with self._lock:
            found = self.transfer(transfer)
            if found is None or found["device"] != device or found["state"] != "waiting":
                return None
            found["arrived"].update(arrived or {})
            found["missing"].extend(identifier for identifier in missing or [] if identifier in found["photos"] and identifier not in found["missing"])
            finished = not self._left(found)
            if finished:
                found["state"] = "done"
            self._write("transfers.json", self.transfers)
            return found if finished else None

    def close(self, transfer: str, entry: str) -> None:
        """Writes on a finished request the name its pictures have in the journal of changes."""
        with self._lock:
            found = self.transfer(transfer)
            if found is not None:
                found["entry"] = entry
                self._write("transfers.json", self.transfers)
