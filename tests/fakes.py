"""What the tests use in place of the real picture model: one that only sees the colour of a picture."""
import base64
import io

import numpy as np
from PIL import Image

COLOURS = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255)}


class ColourEmbedder:
    """A picture becomes its average colour, a sentence becomes the colour it names."""

    name = "colours"

    def __init__(self):
        self.pictures_read = 0

    def images(self, pictures):
        self.pictures_read += len(pictures)
        vectors = [np.asarray(picture.resize((1, 1)), dtype=np.float32).reshape(3) for picture in pictures]
        return np.stack([vector / np.linalg.norm(vector) for vector in vectors])

    def text(self, sentence):
        vector = np.array(next((colour for name, colour in COLOURS.items() if name in sentence), (1, 1, 1)), dtype=np.float32)
        return vector / np.linalg.norm(vector)


def picture(folder, name, colour, day=None):
    """A picture of one colour. With `day`, as "2024-08-15", the camera's note of when it was taken is in it."""
    folder.mkdir(parents=True, exist_ok=True)
    written = Image.Exif()
    if day:
        written[0x0132] = day.replace("-", ":") + " 10:00:00"
    Image.new("RGB", (64, 48), COLOURS[colour]).save(folder / name, exif=written)


def shot(media, colour, name=None, stamp="1", day="2026-08-15"):
    """A picture as a phone sends it: its own name for it, the day it was taken, and a small copy as text."""
    data = io.BytesIO()
    Image.new("RGB", (64, 48), COLOURS[colour]).save(data, "JPEG")
    return {"id": media, "stamp": stamp, "name": name or f"IMG_{media}.jpg", "day": day, "jpeg": base64.b64encode(data.getvalue()).decode()}


def certificate_in(folder):
    """Puts in a folder a certificate that only has to be there: the tests do not make a real one."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "certificate.pem").write_text("-----BEGIN CERTIFICATE-----\n" + base64.b64encode(b"a certificate").decode() + "\n-----END CERTIFICATE-----\n")
    (folder / "key.pem").write_text("a key")
