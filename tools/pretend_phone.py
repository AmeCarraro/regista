"""A pretend phone, to try what the computer does with a real one without having one at hand.

It does what the Android app does: it is let in with the link shown on the page, checks
that the computer is the one the link names, sends a small copy of every picture of a
folder (its "gallery"), and then waits for requests and sends the originals asked for.
When the computer says that pictures may go to the phone's trash, it answers as its user
would with --trash yes or --trash no: with yes the files move to a folder ".cestino" inside
the gallery, which plays the part of the phone's trash. Nothing is ever deleted.

    python tools/pretend_phone.py "regista://pair?..." --gallery some/folder --address 127.0.0.1

It needs Pillow, and nothing else that is not in Python.
"""
import argparse
import base64
import datetime
import hashlib
import http.client
import io
import json
import socket
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from PIL import Image, ImageOps

KINDS = {".jpg", ".jpeg", ".png", ".webp"}
BATCH = 16


class Computer:
    """The computer as the phone reaches it: one address, and the only certificate the phone accepts there."""

    def __init__(self, address: str, port: int, fingerprint: str, key: str = ""):
        self.address, self.port, self.fingerprint, self.key = address, port, fingerprint, key

    def _connect(self) -> http.client.HTTPSConnection:
        # the certificate is the computer's own, signed by nobody: what makes it good is its fingerprint
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(self.address, self.port, context=context, timeout=60)
        connection.connect()
        shown = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        if shown != self.fingerprint:
            connection.close()
            raise SystemExit(f"This is not the computer of the link: its certificate is {shown[:16]}..., the link says {self.fingerprint[:16]}...")
        return connection

    def ask(self, method: str, path: str, body=None, raw: bytes | None = None):
        connection = self._connect()
        try:
            headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
            if raw is not None:
                # what the picture is: the computer checks what arrives against it
                headers["X-Regista-Sha256"] = hashlib.sha256(raw).hexdigest()
            if body is not None:
                raw, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
            connection.request(method, path, body=raw, headers=headers)
            answer = connection.getresponse()
            data = json.loads(answer.read() or b"null")
            if answer.status >= 400:
                raise SystemExit(f"{method} {path} -> {answer.status}: {data}")
            return data
        finally:
            connection.close()


def small_copy(path: Path) -> str:
    picture = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    picture.thumbnail((384, 384))
    data = io.BytesIO()
    picture.save(data, "JPEG", quality=80)
    return base64.b64encode(data.getvalue()).decode()


def day_of(path: Path) -> str:
    """The day a picture was taken: the one written in it, or else the date of the file."""
    try:
        with Image.open(path) as picture:
            written = picture.getexif()
            when = written.get_ifd(0x8769).get(0x9003) or written.get(0x0132)
        if when:
            return datetime.datetime.strptime(str(when)[:10], "%Y:%m:%d").date().isoformat()
    except (OSError, ValueError):
        pass
    return datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()


def position_of(path: Path) -> dict:
    """Where a picture was taken, as {"lat", "lon"} in degrees, if it is written in it; nothing otherwise."""
    try:
        with Image.open(path) as picture:
            written = picture.getexif().get_ifd(0x8825)
        latitude = sum(float(part) / 60 ** power for power, part in enumerate(written[2])) * (-1 if written[1] == "S" else 1)
        longitude = sum(float(part) / 60 ** power for power, part in enumerate(written[4])) * (-1 if written[3] == "W" else 1)
        return {"lat": latitude, "lon": longitude}
    except (OSError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("link", nargs="?", help="the link the page shows when a phone is to be let in; not needed once it has been let in")
    parser.add_argument("--gallery", required=True, type=Path, help="the folder whose pictures play the part of the phone's")
    parser.add_argument("--address", help="where to reach the computer, instead of the addresses in the link")
    parser.add_argument("--name", default="Telefono di prova")
    parser.add_argument("--memory", type=Path, default=Path("pretend_phone.json"), help="where this phone keeps its key, as a real one does")
    parser.add_argument("--once", action="store_true", help="send what is asked for now and stop, instead of waiting for more")
    parser.add_argument("--trash", choices=["yes", "no"], default="no", help="what the user of this phone answers when asked whether pictures may go to its trash")
    arguments = parser.parse_args()
    # line by line also when the output goes to a file: whoever watches it sees what happens as it happens
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    if arguments.link:
        said = {name: values[0] for name, values in parse_qs(urlparse(arguments.link).query).items()}
        addresses = [arguments.address] if arguments.address else said["a"].split(",")
        computer = None
        for address in addresses:
            try:
                socket.create_connection((address, int(said["p"])), timeout=4).close()
                computer = Computer(address, int(said["p"]), said["f"])
                break
            except OSError:
                continue
        if computer is None:
            raise SystemExit(f"The computer does not answer at {', '.join(addresses)} on port {said['p']}")
        paired = computer.ask("POST", "/phone/pair", {"secret": said["s"], "name": arguments.name})
        computer.key = paired["token"]
        arguments.memory.write_text(json.dumps(vars(computer)))
        print(f"let in by {paired['computer'] or computer.address} as {arguments.name}")
    elif arguments.memory.exists():
        computer = Computer(**json.loads(arguments.memory.read_text()))
        print(f"already let in: {computer.ask('GET', '/phone/hello')}")
    else:
        raise SystemExit("This phone was never let in: give it the link the page shows.")

    trash = arguments.gallery / ".cestino"
    files = {path.relative_to(arguments.gallery).as_posix(): path for path in sorted(arguments.gallery.rglob("*"))
             if path.suffix.lower() in KINDS and trash not in path.parents}
    listing = [{"id": name, "stamp": f"{path.stat().st_size}-{int(path.stat().st_mtime)}"} for name, path in files.items()]
    stamps = {item["id"]: item["stamp"] for item in listing}
    wanted = computer.ask("POST", "/phone/library", {"photos": listing})["wanted"]
    print(f"{len(files)} pictures in the gallery, the computer wants a small copy of {len(wanted)}")
    for first in range(0, len(wanted), BATCH):
        batch = [{"id": name, "stamp": stamps[name], "name": files[name].name, "day": day_of(files[name]), **position_of(files[name]), "jpeg": small_copy(files[name])}
                 for name in wanted[first:first + BATCH]]
        computer.ask("POST", "/phone/photos", {"photos": batch})
    computer.ask("POST", "/phone/library/done", {})
    print("small copies sent; waiting for requests" + ("" if arguments.once else " (Ctrl+C to stop)"))

    while True:
        try:
            for transfer in computer.ask("GET", "/phone/work")["transfers"]:
                for photo in transfer["photos"]:
                    path = files.get(photo["media"])
                    if path is None:
                        computer.ask("POST", f"/phone/transfers/{transfer['id']}/missing", {"ids": [photo["id"]]})
                        continue
                    computer.ask("PUT", f"/phone/transfers/{transfer['id']}/photos/{quote(photo['id'])}", raw=path.read_bytes())
                    print(f"sent {path.name}")
                if transfer.get("trash"):
                    moved = []
                    for photo in transfer["trash"] if arguments.trash == "yes" else []:
                        path = files.pop(photo["media"], None)
                        if path is not None and path.exists():
                            trash.mkdir(exist_ok=True)
                            path.rename(trash / path.name)
                        moved.append(photo["id"])
                    computer.ask("POST", f"/phone/transfers/{transfer['id']}/trashed", {"ids": moved, "why": "" if moved else "declined"})
                    print(f"asked about the trash for {len(transfer['trash'])} pictures: {'moved' if moved else 'the user said no'}")
        except OSError as problem:
            # the computer is off or out of reach: a phone keeps trying, it does not give up
            print(f"the computer does not answer ({problem}): trying again")
        if arguments.once:
            return
        time.sleep(2)


if __name__ == "__main__":
    main()
