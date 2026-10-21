"""The real model that reads pictures and sentences, when its files are on this computer (models\\phone): skipped otherwise."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from embedder import ClipEmbedder, WordPieces

MODELS = Path(__file__).resolve().parent.parent / "models" / "phone"
SAMPLES = Path(__file__).resolve().parent.parent / "foto" / "esempi"
needs_models = pytest.mark.skipif(not (MODELS / "vision.onnx").is_file(), reason="the model's files are not on this computer")


@needs_models
def test_words_are_cut_into_the_pieces_the_model_knows():
    pieces = WordPieces(MODELS / "vocab.txt")

    ids = pieces.encode("trovami un cane nero")

    words = list(pieces.ids)
    assert words[ids[0]] == "[CLS]" and words[ids[-1]] == "[SEP]"
    assert "".join(words[index].removeprefix("##") for index in ids[1:-1]) == "trovamiuncanenero"


@needs_models
def test_a_picture_is_read_the_same_alone_or_with_others_and_a_sentence_finds_it():
    model = ClipEmbedder(MODELS)
    pictures = [Image.open(SAMPLES / f"{number:03d}.jpg") for number in range(0, 200, 20)]

    together = model.images(pictures)
    alone = model.images(pictures[3:4])[0]

    assert together.shape == (10, 512) and np.allclose(np.linalg.norm(together, axis=1), 1, atol=1e-5)
    assert float(together[3] @ alone) > 0.9999
    # the same sentence in Italian and in English lands close to the same pictures
    assert float(model.text("un cane") @ model.text("a dog")) > 0.8


def test_missing_files_are_said_plainly(tmp_path):
    with pytest.raises(FileNotFoundError, match="install.cmd"):
        ClipEmbedder(tmp_path).text("a dog")
