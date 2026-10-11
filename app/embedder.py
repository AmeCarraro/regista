"""The model that reads pictures and sentences: CLIP ViT-B/32, on the processor.

It turns a picture or a sentence into 512 numbers, in such a way that a picture and a
sentence that describes it get similar numbers. It understands English far better than
other languages, so sentences reach it already translated (see orchestrator.py).
It is loaded the first time it is needed: importing it takes seconds and a lot of memory.
"""
import threading

import numpy as np

# "quickgelu" is the variant these weights were trained with: the plain name gives slightly worse fingerprints
MODEL = "ViT-B-32-quickgelu"
WEIGHTS = "openai"


class ClipEmbedder:
    # written next to the fingerprints: a different model means they must be made again
    name = f"{MODEL}/{WEIGHTS}"

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                import open_clip
                import torch

                self._torch = torch
                model, _, self._preprocess = open_clip.create_model_and_transforms(MODEL, pretrained=WEIGHTS)
                self._tokenizer = open_clip.get_tokenizer(MODEL)
                self._model = model.eval()
        return self._model

    def _unit(self, vectors) -> np.ndarray:
        """Vectors of length 1: the product of two of them is then how similar they are."""
        vectors = vectors / vectors.norm(dim=-1, keepdim=True)
        return vectors.cpu().numpy().astype(np.float32)

    def images(self, pictures: list) -> np.ndarray:
        model = self._load()
        with self._torch.no_grad():
            batch = self._torch.stack([self._preprocess(picture) for picture in pictures])
            return self._unit(model.encode_image(batch))

    def text(self, sentence: str) -> np.ndarray:
        model = self._load()
        with self._torch.no_grad():
            return self._unit(model.encode_text(self._tokenizer([sentence])))[0]
