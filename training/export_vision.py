"""Export the experimental photo tagger to ONNX and check CPU inference parity."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import onnx
import onnxruntime as ort
import torch
from torch import nn

from onnx_weights import compact_weights
from vision import CLASSES, PhotoTagger, normalize, read_cifar, unpack


INPUT = "pixels"
OUTPUT = "class_logits"
OPSET = 17
SAMPLE_COUNT = 128


class ImageInput(nn.Module):
    def __init__(self, tagger):
        super().__init__()
        self.tagger = tagger

    def forward(self, pixels):
        return self.tagger(normalize(pixels))


def verify(tagger, payload, archive, compact):
    onnx.checker.check_model(payload)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    runtime = ort.InferenceSession(payload, options, providers=["CPUExecutionProvider"])
    _, test = read_cifar(archive)
    generator = torch.Generator().manual_seed(42)
    sample = test[torch.randperm(len(test), generator=generator)[:SAMPLE_COUNT]]
    images, _ = unpack(sample, "cpu")

    maximum_error = 0.0
    for batch in (images[:1], images[1:]):
        expected = tagger(normalize(batch))
        actual = torch.from_numpy(runtime.run([OUTPUT], {INPUT: batch.numpy()})[0])
        torch.testing.assert_close(actual, expected, atol=0.02 if compact else 1e-4, rtol=1e-4)
        if not torch.equal(actual.argmax(1), expected.argmax(1)):
            raise ValueError("ONNX and PyTorch assigned different image tags")
        maximum_error = max(maximum_error, float((actual - expected).abs().max()))
    return {"examples": len(images), "matching_top_labels": len(images), "max_logit_error": maximum_error}


@torch.inference_mode()
def export(checkpoint, archive, out, compact=False):
    torch.set_num_threads(2)
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if tuple(saved["classes"]) != CLASSES:
        raise ValueError("Unexpected label order in the photo checkpoint")
    tagger = PhotoTagger()
    tagger.load_state_dict(saved["state"])
    model = ImageInput(tagger).eval()
    buffer = BytesIO()
    torch.onnx.export(
        model, (torch.zeros(1, 3, 32, 32, dtype=torch.uint8),), buffer,
        input_names=[INPUT], output_names=[OUTPUT], opset_version=OPSET, dynamo=False,
        dynamic_axes={INPUT: {0: "batch"}, OUTPUT: {0: "batch"}},
    )
    payload = buffer.getvalue()
    if compact:
        payload = compact_weights(payload)
    parity = verify(tagger, payload, archive, compact)

    metadata = {
        "format_version": 1,
        "opset": OPSET,
        "model_sha256": sha256(payload).hexdigest(),
        "weights_type": "float16" if compact else "float32",
        "input": {"name": INPUT, "type": "uint8", "shape": ["batch", 3, 32, 32],
                  "layout": "NCHW", "color_order": "RGB", "value_range": [0, 255],
                  "normalization_in_model": "float32(pixels) / 127.5 - 1"},
        "output": {"name": OUTPUT, "type": "float32", "shape": ["batch", len(CLASSES)],
                   "labels": CLASSES},
        "parity": parity,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "photo-tagger.onnx").write_bytes(payload)
    (out / "photo-tagger.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "onnx_bytes": len(payload), **parity}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path("build/vision/photo-tagger.pt"))
    parser.add_argument("--archive", type=Path, default=Path("build/vision-data/cifar-10-binary.tar.gz"))
    parser.add_argument("--out", type=Path, default=Path("build/vision-onnx"))
    parser.add_argument("--compact", action="store_true", help="Store weights in float16 and run in float32")
    args = parser.parse_args()
    export(args.checkpoint, args.archive, args.out, args.compact)
