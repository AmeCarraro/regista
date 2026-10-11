"""What the tests use in place of the real picture model: one that only sees the colour of a picture."""
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


def picture(folder, name, colour):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), COLOURS[colour]).save(folder / name)
