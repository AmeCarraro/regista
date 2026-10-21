"""The model that reads pictures and sentences: the same two small ones the phone runs (Sight.kt).

A picture becomes 512 numbers through CLIP ViT-B/32 (OpenAI's, made small: quantized to 8 bits),
and a sentence through a model taught to answer as CLIP's own does, in fifty languages
(sentence-transformers clip-ViT-B-32-multilingual-v1), so that a picture and a sentence that
describes it get similar numbers. Both run in ONNX Runtime, on the processor: no PyTorch, about
220 MB of files that the phone takes from here too, where PyTorch and CLIP took 1.6 GB.

Measured on the 200 sample pictures with 20 captions as the director writes them: 365 right of
400 in the first 20 of each, where CLIP of PyTorch had 374. The files are kept in a folder of
their own (PHONE_MODELS), downloaded once with their SHA-256 checked (tools/phone-models.ps1).
"""
import json
import os
import struct
import threading
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image

# written next to the fingerprints: a different model means they must be made again
NAME = "clip-vit-b32-q8+multilingual-v1"
# how many pieces of words a sentence can have; the model was taught on no more
MAX_TOKENS = 128
# how a picture is made ready for the model: what CLIP was taught with
SIDE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def _punctuation(char: str) -> bool:
    code = ord(char)
    return 33 <= code <= 47 or 58 <= code <= 64 or 91 <= code <= 96 or 123 <= code <= 126 or unicodedata.category(char).startswith("P")


def _chinese(code: int) -> bool:
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x20000 <= code <= 0x2A6DF or 0x2A700 <= code <= 0x2B73F
            or 0x2B740 <= code <= 0x2B81F or 0x2B820 <= code <= 0x2CEAF or 0xF900 <= code <= 0xFAFF or 0x2F800 <= code <= 0x2FA1F)


class WordPieces:
    """Words into numbers, BERT's way, for a model that keeps capitals and accents: the phone does the same (Sight.kt)."""

    def __init__(self, vocab: Path):
        self.ids = {line.rstrip("\n"): index for index, line in enumerate(vocab.read_text(encoding="utf-8").splitlines())}

    def words(self, text: str) -> list[str]:
        cleaned = []
        for char in text:
            code = ord(char)
            if code == 0 or code == 0xFFFD or (unicodedata.category(char).startswith("C") and char not in "\t\n\r"):
                continue
            if _chinese(code):
                cleaned.append(f" {char} ")
            elif char in " \t\n\r" or unicodedata.category(char) == "Zs":
                cleaned.append(" ")
            else:
                cleaned.append(char)
        words = []
        for word in "".join(cleaned).split():
            piece = ""
            for char in word:
                if _punctuation(char):
                    if piece:
                        words.append(piece)
                    words.append(char)
                    piece = ""
                else:
                    piece += char
            if piece:
                words.append(piece)
        return words

    def pieces(self, word: str) -> list[int]:
        if len(word) > 100:
            return [self.ids["[UNK]"]]
        found, start = [], 0
        while start < len(word):
            end, match = len(word), None
            while start < end:
                piece = ("##" if start > 0 else "") + word[start:end]
                if piece in self.ids:
                    match = self.ids[piece]
                    break
                end -= 1
            if match is None:
                return [self.ids["[UNK]"]]
            found.append(match)
            start = end
        return found

    def encode(self, text: str) -> list[int]:
        ids = [self.ids["[CLS]"]]
        for word in self.words(text):
            ids += self.pieces(word)
        return ids[: MAX_TOKENS - 1] + [self.ids["[SEP]"]]


def _dense(file: Path) -> np.ndarray:
    """The last layer of the sentence model, read from its safetensors file: 512 rows of 768."""
    data = file.read_bytes()
    size = struct.unpack("<Q", data[:8])[0]
    weight = json.loads(data[8:8 + size])["linear.weight"]
    start, end = weight["data_offsets"]
    return np.frombuffer(data[8 + size + start:8 + size + end], dtype="<f4").reshape(weight["shape"])


def _unit(vectors: np.ndarray) -> np.ndarray:
    """Vectors of length 1: the product of two of them is then how similar they are."""
    return (vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)).astype(np.float32)


def _ready(picture: Image.Image) -> np.ndarray:
    """A picture as CLIP was taught to see it: the shorter side to 224, the middle square, the colours in its scale."""
    picture = picture.convert("RGB")
    scale = SIDE / min(picture.size)
    picture = picture.resize((max(SIDE, round(picture.width * scale)), max(SIDE, round(picture.height * scale))), Image.BICUBIC)
    left, top = (picture.width - SIDE) // 2, (picture.height - SIDE) // 2
    values = np.asarray(picture.crop((left, top, left + SIDE, top + SIDE)), dtype=np.float32) / 255
    return ((values - MEAN) / STD).transpose(2, 0, 1)


class ClipEmbedder:
    name = NAME

    def __init__(self, folder: str | Path = os.getenv("PHONE_MODELS", "/models/phone")):
        self.folder = Path(folder)
        self._models = None
        self._lock = threading.Lock()

    def _load(self):
        """The two models, the first time they are needed. Missing files are said plainly: the page shows it."""
        with self._lock:
            if self._models is None:
                import onnxruntime

                missing = [name for name in ("vision.onnx", "text.onnx", "vocab.txt", "dense.safetensors") if not (self.folder / name).is_file()]
                if missing:
                    raise FileNotFoundError(f"mancano i file del modello che legge le foto ({', '.join(missing)}): rilancia install.cmd")
                options = onnxruntime.SessionOptions()
                options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
                run = ["CPUExecutionProvider"]
                self._models = (
                    onnxruntime.InferenceSession(str(self.folder / "vision.onnx"), options, providers=run),
                    onnxruntime.InferenceSession(str(self.folder / "text.onnx"), options, providers=run),
                    WordPieces(self.folder / "vocab.txt"),
                    _dense(self.folder / "dense.safetensors"),
                )
        return self._models

    def images(self, pictures: list) -> np.ndarray:
        vision = self._load()[0]
        # One at a time: a model made small reads a picture a little differently next to others (0.98 instead
        # of 1). Alone, a picture gets the same numbers here as on the phone, whatever else is being read.
        return _unit(np.stack([vision.run(None, {"pixel_values": _ready(picture)[None]})[0][0] for picture in pictures]))

    def text(self, sentence: str) -> np.ndarray:
        _, words, tokens, projection = self._load()
        ids = np.array([tokens.encode(sentence)], dtype=np.int64)
        hidden = words.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})[0][0]
        # the mean of the words' numbers, then the last layer, as sentence-transformers does
        return _unit(projection @ hidden.mean(axis=0))
