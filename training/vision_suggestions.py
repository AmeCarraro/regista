"""Measure how often the visual tagger can suggest a label at a chosen precision."""

import argparse
import json
from pathlib import Path

import torch

from vision import CLASSES, PhotoTagger, normalize, read_cifar, split_data, unpack


@torch.inference_mode()
def scores(model, records):
    images, labels = unpack(records, "cpu")
    predictions = [model(normalize(batch)).softmax(1).max(1) for batch in images.split(256)]
    confidence = torch.cat([batch.values for batch in predictions])
    correct = torch.cat([batch.indices for batch in predictions]).eq(labels)
    return confidence, correct


def measure(confidence, correct, threshold):
    offered = confidence.ge(threshold)
    accepted = int(offered.sum())
    right = int((offered & correct).sum())
    return {"examples": len(correct), "suggested": accepted, "correct": right,
            "coverage": accepted / len(correct), "precision": right / accepted if accepted else None}


def choose_threshold(confidence, correct, target):
    for step in range(101):
        threshold = step / 100
        result = measure(confidence, correct, threshold)
        if result["precision"] is not None and result["precision"] >= target:
            return threshold
    return None


def run(args):
    torch.set_num_threads(2)
    training_report = json.loads((args.checkpoint.parent / "metrics.json").read_text(encoding="utf-8"))
    saved = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if tuple(saved["classes"]) != CLASSES:
        raise ValueError("Unexpected label order in the photo checkpoint")
    model = PhotoTagger().eval()
    model.load_state_dict(saved["state"])

    training, test = read_cifar(args.archive)
    _, validation = split_data(training, training_report["seed"])
    confidence, correct = scores(model, validation)
    threshold = choose_threshold(confidence, correct, args.precision)
    report = {"target_precision": args.precision, "threshold": threshold}
    if threshold is not None:
        report["validation"] = measure(confidence, correct, threshold)
        report["test"] = measure(*scores(model, test), threshold)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path("build/vision/photo-tagger.pt"))
    parser.add_argument("--archive", type=Path, default=Path("build/vision-data/cifar-10-binary.tar.gz"))
    parser.add_argument("--precision", type=float, default=0.90)
    parser.add_argument("--out", type=Path, default=Path("build/vision/suggestions.json"))
    args = parser.parse_args()
    if not 0 < args.precision <= 1:
        parser.error("--precision must be between 0 (exclusive) and 1")
    run(args)
