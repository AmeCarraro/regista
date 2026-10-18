"""The phones that may talk to this computer, and what the computer knows of their pictures.

A phone is let in once, with a link that only this computer knows and shows as a QR code:
from then on the phone proves who it is with a key of its own. What a phone sends is a
small copy of each of its pictures. The computer reads them as it reads its own, so they
can be searched here; the pictures themselves stay on the phone until the user asks for
some. Then the computer asks, and the phone sends the originals.

Pictures go the other way too: the computer prepares some of its own for a phone, and the
phone takes them into an album of its own when its app is open, checking each against what
the computer says it is. And a phone can ask the computer to take some of its pictures.

The user can also ask to take pictures off the phone. Then the originals come here first,
each checked against what the phone says it sent, and only the ones that arrived whole are
named to the phone as pictures it may move to its own trash. Whether it does is for the
user to say once more, on the phone, to Android itself.

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
from photos import BATCH, THUMB, closest, look_of, twins

# How long the code that lets a phone ask to come in stays good: the page shows a new one every half
# minute, so a picture taken of the screen is soon of no use.
INVITE_SECONDS = 60
# how long a phone that showed a good code waits for the user's yes on this computer
PENDING_SECONDS = 120
# more refused knocks than this in a minute, and for a minute the door answers only the phones it knows
KNOCKS = 30
# the largest small copy a phone may send, as text: a 384-pixel JPEG is a tenth of this
SMALL_COPY = 600_000
# and the most pixels it may have: a phone of ours sends 384 on the long side
SMALL_COPY_PIXELS = 1600 * 1600
# what a file that arrives from a phone may end in
ENDINGS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "gif", "avif", "dng"}
# the first Android with a trash an app can ask for: 11
TRASH_SINCE = 30
# The model whose fingerprints a phone can keep as its own: the phone looks at pictures with the same
# one, CLIP ViT-B/32 as OpenAI made it (Sight.kt), so the numbers of one can be compared with the other's.
SHARED_MODEL = "ViT-B-32-quickgelu/openai"


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
        # the secrets of the codes on show, with when each stops being good
        self._invites: dict[str, float] = {}
        # the phones that showed a good code and wait for the user's yes, by the name of their request
        self._pending: dict[str, dict] = {}
        # the knocks at the door of the phones that were refused, the last ones, and how many in all
        self.refused: list[dict] = []
        self._refusals = 0
        self._calm_until = 0.0
        self._saved = 0.0
        self.devices: list[dict] = self._read("devices.json", [])
        # the pictures of every phone: {"id", "device", "media" (the phone's own name for it), "stamp", "name", "day"}
        self.photos: list[dict] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.transfers: list[dict] = self._read("transfers.json", [])
        # pictures of this computer on their way to a phone
        self.sends: list[dict] = self._read("sends.json", [])
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
        """A new code that lets one phone ask to come in, good for a minute. The ones before stay good until their time is up."""
        secret = secrets.token_urlsafe(18)
        now = time.monotonic()
        with self._lock:
            self._invites = {known: until for known, until in self._invites.items() if until > now}
            self._invites[secret] = now + INVITE_SECONDS
        query = urlencode({"a": ",".join(self.addresses), "p": self.port, "s": secret, "f": self.fingerprint(), "n": self.computer})
        return {"link": f"regista://pair?{query}", "seconds": INVITE_SECONDS}

    def _tidy(self) -> None:
        """Forgets the requests whose time is up. A phone that was let in and never took its key is shut out again."""
        now = time.monotonic()
        for request in [one for one in self._pending.values() if one["until"] <= now]:
            del self._pending[request["id"]]
            if request["state"] == "accepted":
                self.devices = [device for device in self.devices if device["id"] != request["device"]]
                self._write("devices.json", self.devices)

    def pair(self, secret: str, name: str) -> dict:
        """A phone shows the secret of a code still good: it is put to wait for the user's yes on this computer.

        It gets a ticket, to ask whether the yes came, and a number of six figures that the user sees here
        and on the phone, so that the phone let in is the one in the user's hand. The codes on show stop
        being good: one phone at a time.
        """
        now = time.monotonic()
        with self._lock:
            self._tidy()
            good = any(until > now and secrets.compare_digest(secret.encode(), known.encode()) for known, until in self._invites.items())
            if not good:
                self._knocked("un codice di collegamento sbagliato o scaduto")
                raise Refused("Questo collegamento non vale più: fanne uno nuovo dal computer.")
            self._invites = {}
            ticket = secrets.token_urlsafe(32)
            request = {
                "id": secrets.token_hex(4),
                # the ticket itself is not kept: only what proves that a ticket is the right one
                "ticket": hashlib.sha256(ticket.encode()).hexdigest(),
                "name": re.sub(r"[\x00-\x1f]", " ", name).strip()[:40] or "Telefono",
                "code": f"{secrets.randbelow(1_000_000):06d}",
                "until": now + PENDING_SECONDS,
                "state": "waiting",
            }
            self._pending[request["id"]] = request
            return {"ticket": ticket, "code": request["code"], "computer": self.computer, "seconds": PENDING_SECONDS}

    def waiting(self) -> list[dict]:
        """The phones that wait for the user's yes, as the page shows them: the name each gives itself, and its number."""
        with self._lock:
            self._tidy()
            now = time.monotonic()
            return [{"id": one["id"], "name": one["name"], "code": one["code"], "seconds": int(one["until"] - now)}
                    for one in self._pending.values() if one["state"] == "waiting"]

    def answer(self, request: str, yes: bool) -> bool:
        """The user's answer, on this computer, to a phone that asks to come in. With a yes it is let in, with a key of its own."""
        with self._lock:
            self._tidy()
            one = self._pending.get(request)
            if one is None or one["state"] != "waiting":
                return False
            if not yes:
                one["state"] = "refused"
                return True
            token = secrets.token_urlsafe(32)
            device = {
                "id": secrets.token_hex(4),
                "name": one["name"],
                # the key itself is not kept: only what proves that a key is the right one
                "key": hashlib.sha256(token.encode()).hexdigest(),
                "paired": _now(),
                "seen": _now(),
            }
            self.devices.append(device)
            self._write("devices.json", self.devices)
            # the key waits here, in memory only, until the phone takes it with its ticket
            one.update(state="accepted", token=token, device=device["id"])
            return True

    def collect(self, ticket: str) -> dict:
        """What a phone that asked to come in learns with its ticket: that it still waits, or, once, its key."""
        mark = hashlib.sha256(ticket.encode()).hexdigest()
        with self._lock:
            self._tidy()
            one = next((one for one in self._pending.values() if secrets.compare_digest(one["ticket"], mark)), None)
            if one is None:
                self._knocked("una richiesta di collegamento che non c'era")
                raise Refused("Questa richiesta non vale più: rifai il collegamento dal computer.")
            if one["state"] == "waiting":
                return {"state": "waiting", "seconds": int(one["until"] - time.monotonic())}
            del self._pending[one["id"]]
            if one["state"] == "refused":
                raise Refused("Sul computer hanno detto di no: questo telefono non è collegato.")
            return {"state": "paired", "token": one["token"], "device": one["device"], "computer": self.computer}

    # ---- the knocks that were refused

    def knocked(self, what: str) -> None:
        """Notes a knock at the door of the phones that was refused, and why. Many in a short time, and the door calms down for a minute."""
        with self._lock:
            self._knocked(what)

    def _knocked(self, what: str) -> None:
        now = time.monotonic()
        self._refusals += 1
        self.refused = [*self.refused[-49:], {"when": _now(), "what": what, "at": now}]
        if sum(1 for one in self.refused if now - one["at"] < 60) > KNOCKS:
            self._calm_until = now + 60

    @property
    def calm(self) -> bool:
        """Whether, for a while, the door answers only the phones it knows: too many knocks were refused."""
        return time.monotonic() < self._calm_until

    def knocks(self) -> dict:
        """The knocks refused since this computer started, as the page shows them: how many, and the last one."""
        with self._lock:
            last = self.refused[-1] if self.refused else {"when": "", "what": ""}
            return {"count": self._refusals, "last": last["when"], "what": last["what"]}

    def device_of(self, token: str) -> dict | None:
        """The phone a key belongs to, if it is the key of a phone that was let in."""
        key = hashlib.sha256(token.encode()).hexdigest()
        device = next((device for device in self.devices if secrets.compare_digest(device["key"], key)), None)
        if device:
            device["seen"] = _now()
        return device

    def running(self, device: dict, android: str) -> None:
        """Notes the version of Android a phone says it runs: what can be done with its pictures depends on it."""
        # a number of a few figures, and nothing else: what a phone sends is not trusted to be one
        if re.fullmatch("[0-9]{1,3}", android) and device.get("android") != int(android):
            with self._lock:
                device["android"] = int(android)
                self._write("devices.json", self.devices)

    def can_trash(self, identifiers: list[str]) -> bool:
        """Whether the phones these pictures are on have a trash an app can ask for: from Android 11. A phone that has not said is taken to."""
        with self._lock:
            devices = {photo["device"] for photo in self.photos if photo["id"] in set(identifiers)}
            return all(device.get("android", TRASH_SINCE) >= TRASH_SINCE for device in self.devices if device["id"] in devices)

    def forget_device(self, device: str) -> bool:
        """Shuts a phone out: its key stops working, and what was known of its pictures is dropped."""
        with self._lock:
            if not any(known["id"] == device for known in self.devices):
                return False
            self.devices = [known for known in self.devices if known["id"] != device]
            self._drop({photo["id"] for photo in self.photos if photo["device"] == device})
            for transfer in self.transfers + self.sends:
                if transfer["device"] == device and transfer["state"] != "done":
                    transfer["state"] = "done"
            self._write("devices.json", self.devices)
            self._write("transfers.json", self.transfers)
            self._write("sends.json", self.sends)
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
                    # pictures waited for from the phone, and pictures that wait for it here
                    "waiting": sum(len(self._left(transfer)) for transfer in self.transfers if transfer["device"] == device["id"] and transfer["state"] == "waiting")
                    + sum(len(self._undelivered(one)) for one in self.sends if one["device"] == device["id"] and one["state"] == "waiting"),
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

    def vectors_of(self, device: str, listing: list[dict]) -> dict[str, str]:
        """What this computer has read in some pictures of a phone, for the phone to keep as its own.

        By the phone's own name for each picture, as base64 of 512 numbers (float32, little-endian);
        only for a picture as the phone has it now (the same "stamp"), and only when the numbers were
        made by the model the phone looks with.
        """
        if self.embedder.name != SHARED_MODEL:
            return {}
        asked = {str(item["id"]): str(item.get("stamp", "")) for item in listing}
        with self._lock:
            return {
                photo["media"]: base64.b64encode(self.vectors[position].astype("<f4").tobytes()).decode()
                for position, photo in enumerate(self.photos)
                if photo["device"] == device and asked.get(photo["media"]) == photo["stamp"]
            }

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
            # how it looks in pixels, to tell a copy of a picture from another picture of the same thing
            look = look_of(picture)
            media = str(item["id"])
            day = str(item.get("day", ""))
            position = self._position(item)
            country, region = self.places.where(position) if self.places else ("", "")
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
                "country": country,
                "region": region,
                "look": look,
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

    def search(self, description: str, limit: int = 60, period: tuple | None = None, spot: dict | None = None, device: str | None = None) -> dict:
        """The pictures of the phones closest to a sentence, or of one phone only: the same answer the pictures of this computer give."""
        with self._lock:
            photos, vectors = self.photos, self.vectors
        if device is not None:
            mine = [position for position, photo in enumerate(photos) if photo["device"] == device]
            photos, vectors = [photos[position] for position in mine], (vectors[mine] if mine else vectors[:0])
        if not photos:
            return closest(vectors, None, [], limit)
        if spot and spot["kind"] == "region" and self.places:
            # pictures kept before regions were known get theirs from the position they have
            for photo in photos:
                if "region" not in photo:
                    photo["region"] = self.places.where((photo["lat"], photo["lon"]) if photo.get("lat") is not None else None)[1]
        only = self.places.inside(spot, photos) if spot and self.places else None
        return closest(vectors, self.embedder.text(description) if description else None, photos, limit, period, only)

    def twins(self, period: tuple | None = None) -> list[list[dict]]:
        """The pictures of the phones that are copies of one another, in groups, the one to keep first: each {"id", "name", "day"}.

        Only within one phone: a copy on another phone is not one too many.
        """
        with self._lock:
            photos, vectors = list(self.photos), self.vectors
        for photo in photos:
            if "look" not in photo:
                # a picture kept before looks were: its small copy here tells it
                small = self.folder / "thumbs" / f"{photo['id']}.jpg"
                try:
                    with Image.open(small) as picture:
                        photo["look"] = look_of(picture)
                except OSError:
                    photo["look"] = ""
        groups = []
        for device in {photo["device"] for photo in photos}:
            mine = [position for position, photo in enumerate(photos) if photo["device"] == device]
            found = twins([photos[position] for position in mine], vectors[mine], period)
            groups += [[{key: photos[mine[at]].get(key, "") for key in ("id", "name", "day")} for at in group] for group in found]
        return groups

    def thumbnail(self, identifier: str) -> bytes | None:
        file = self.folder / "thumbs" / f"{identifier}.jpg"
        known = any(photo["id"] == identifier for photo in self.photos)
        return file.read_bytes() if known and file.exists() else None

    # ---- asking a phone for the originals

    def _left(self, transfer: dict) -> list[str]:
        known = {photo["id"] for photo in self.photos}
        # a picture the phone no longer has cannot arrive: it is not waited for
        return [identifier for identifier in transfer["photos"] if identifier in known and identifier not in transfer["arrived"] and identifier not in transfer["missing"]]

    def ask(self, identifiers: list[str], folder: str, then: str = "") -> dict:
        """Asks a phone for the originals of some of its pictures, to go into a folder of the collections.

        Nothing arrives now: the phone answers when its app is open. One phone at a time.
        With `then` "trash", the phone is afterwards asked to move to its trash the pictures
        that arrived here whole.
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
                # "waiting" for the originals, then "done"; in between, when the pictures are to leave the phone,
                # "confirming": the copies are here and the phone is asking its user
                "state": "waiting",
                "asked": _now(),
                # the name of the change in the journal, once everything has arrived
                "entry": "",
                "then": then,
                # the pictures the phone moved to its trash, and why it moved none if it did not
                "trashed": [],
                "why": "",
            }
            self.transfers.append(transfer)
            self._write("transfers.json", self.transfers)
            return transfer

    def transfer(self, identifier: str) -> dict | None:
        return next((transfer for transfer in self.transfers if transfer["id"] == identifier), None)

    def work(self, device: str) -> list[dict]:
        """What a phone is asked to do: for every request still open, the pictures to send that have
        not arrived yet and, once they all have, the ones it may move to its trash."""
        with self._lock:
            media = {photo["id"]: photo["media"] for photo in self.photos}

            def named(identifiers) -> list[dict]:
                return [{"id": identifier, "media": media[identifier]} for identifier in identifiers if identifier in media]

            return [
                {
                    "id": transfer["id"],
                    "then": transfer.get("then", ""),
                    "photos": named(self._left(transfer)) if transfer["state"] == "waiting" else [],
                    # only what is safely here
                    "trash": named(transfer["arrived"]) if transfer["state"] == "confirming" else [],
                }
                for transfer in self.transfers
                if transfer["device"] == device and transfer["state"] != "done"
            ]

    def expected(self, transfer: str, device: str, identifier: str) -> dict:
        """The picture a phone is about to send, if it was asked for and has not arrived yet. Anything else is refused."""
        with self._lock:
            found = self.transfer(transfer)
            if found is None or found["device"] != device or found["state"] != "waiting" or identifier not in self._left(found):
                raise Refused("Questa foto non è stata chiesta.")
            return {"folder": found["folder"], "name": next(photo["name"] for photo in self.photos if photo["id"] == identifier), "then": found.get("then", "")}

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
                # pictures that are to leave the phone, and are here: now it is for the phone to ask its user
                found["state"] = "confirming" if found.get("then") == "trash" and found["arrived"] else "done"
            self._write("transfers.json", self.transfers)
            return found if finished else None

    def trashed(self, transfer: str, device: str, identifiers: list[str], why: str = "") -> dict | None:
        """Notes what a phone did with the pictures it could move to its trash: which ones it moved, or why none.

        Only pictures that had arrived here count, whatever the phone says. They are no
        longer among the pictures of the phone.
        """
        with self._lock:
            found = self.transfer(transfer)
            if found is None or found["device"] != device or found["state"] != "confirming":
                return None
            found["trashed"] = [identifier for identifier in dict.fromkeys(identifiers) if identifier in found["arrived"]]
            found["why"] = "" if found["trashed"] else why
            found["state"] = "done"
            self._drop(set(found["trashed"]))
            self._write("transfers.json", self.transfers)
            self.save()
            return found

    # ---- pictures of this computer sent to a phone

    def receiver(self) -> dict | None:
        """The phone pictures are sent to: the one seen last, if more than one was let in."""
        with self._lock:
            return max(self.devices, key=lambda device: device["seen"], default=None)

    def send(self, device: str, pictures: list[dict], folder: str) -> dict:
        """Prepares pictures of this computer for a phone, which takes them into an album when its app is open.

        `pictures` holds, for each, its short name here and the name of its file. Nothing
        leaves now, and nothing here changes.
        """
        with self._lock:
            sending = {
                "id": secrets.token_hex(6),
                "device": device,
                "folder": folder,
                "photos": [picture["id"] for picture in pictures],
                "names": {picture["id"]: file_name(picture["name"]) for picture in pictures},
                # the pictures the phone took, and the ones it could not
                "received": [],
                "missing": [],
                "state": "waiting",
                "asked": _now(),
            }
            self.sends.append(sending)
            self._write("sends.json", self.sends)
            return sending

    def sending(self, identifier: str) -> dict | None:
        return next((one for one in self.sends if one["id"] == identifier), None)

    @staticmethod
    def _undelivered(sending: dict) -> list[str]:
        return [identifier for identifier in sending["photos"] if identifier not in sending["received"] and identifier not in sending["missing"]]

    def incoming(self, device: str) -> list[dict]:
        """What a phone is to take from this computer: for every sending still open, the pictures it has not taken yet."""
        with self._lock:
            return [
                {"id": one["id"], "folder": one["folder"], "photos": [{"id": identifier, "name": one["names"][identifier]} for identifier in self._undelivered(one)]}
                for one in self.sends
                if one["device"] == device and one["state"] == "waiting"
            ]

    def offered(self, sending: str, device: str, identifier: str) -> bool:
        """Whether a phone may take a picture: it was sent to that phone, and it has not taken it yet."""
        with self._lock:
            found = self.sending(sending)
            return found is not None and found["device"] == device and found["state"] == "waiting" and identifier in self._undelivered(found)

    def delivered(self, sending: str, device: str, received: list[str], missing: list[str]) -> dict | None:
        """Notes which pictures a phone took, and which it could not. Returns the sending, if this ended it."""
        with self._lock:
            found = self.sending(sending)
            if found is None or found["device"] != device or found["state"] != "waiting":
                return None
            left = set(self._undelivered(found))
            found["received"] += [identifier for identifier in dict.fromkeys(received) if identifier in left]
            found["missing"] += [identifier for identifier in dict.fromkeys(missing) if identifier in left and identifier not in found["received"]]
            if not self._undelivered(found):
                found["state"] = "done"
            self._write("sends.json", self.sends)
            return found if found["state"] == "done" else None

    def close(self, transfer: str, entry: str) -> None:
        """Writes on a finished request the name its pictures have in the journal of changes."""
        with self._lock:
            found = self.transfer(transfer)
            if found is not None:
                found["entry"] = entry
                self._write("transfers.json", self.transfers)
