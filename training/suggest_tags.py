"""Try the local vision model on individual images without editing the catalog."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps


def load(bundle):
    metadata = json.loads((bundle / "photo-tagger.json").read_text(encoding="utf-8"))
    payload = (bundle / "photo-tagger.onnx").read_bytes()
    if sha256(payload).hexdigest() != metadata["model_sha256"]:
        raise ValueError("The photo model does not match its metadata")
    if (metadata["format_version"] != 1 or metadata["input"]["shape"] != ["batch", 3, 32, 32]
            or metadata["input"]["type"] != "uint8" or metadata["input"]["color_order"] != "RGB"
            or metadata["input"]["layout"] != "NCHW"):
        raise ValueError("Unsupported photo model format")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(payload, options, providers=["CPUExecutionProvider"]), metadata


def suggest(runtime, metadata, picture, threshold):
    with Image.open(picture) as image:
        fitted = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), (32, 32), Image.Resampling.BILINEAR)
        pixels = np.asarray(fitted, dtype=np.uint8).transpose(2, 0, 1)[None, ...]
    scores = runtime.run([metadata["output"]["name"]], {metadata["input"]["name"]: pixels})[0][0]
    probabilities = np.exp(scores - scores.max())
    best = int(probabilities.argmax())
    confidence = float(probabilities[best] / probabilities.sum())
    return {"image": str(picture), "suggested_tag": metadata["output"]["labels"][best] if confidence >= threshold else None,
            "score": confidence}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--bundle", type=Path, default=Path("build/vision-onnx"))
    parser.add_argument("--threshold", type=float, default=0.60)
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    runtime, metadata = load(args.bundle)
    for picture in args.images:
        print(json.dumps(suggest(runtime, metadata, picture, args.threshold), ensure_ascii=False))
