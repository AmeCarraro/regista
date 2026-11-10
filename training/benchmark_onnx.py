"""Compare size, latency and decoded output of local command bundles on the PC."""

import argparse
import json
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

from commands_data import examples
from commands_fresh import examples as fresh_examples
from commands_manual import examples as manual_examples
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from command_model import CommandModel


def run(bundle, requests, repetitions):
    start = perf_counter()
    model = CommandModel(bundle)
    initialized = perf_counter()
    model.ask(requests[0])
    first = perf_counter()
    times = []
    decoded = []
    for repetition in range(repetitions):
        for request in requests:
            start_request = perf_counter()
            answer = model.ask(request)
            times.append(1000 * (perf_counter() - start_request))
            if repetition == 0:
                decoded.append(answer)
    model_bytes = (bundle / "commands.onnx").stat().st_size
    return decoded, {
        "bundle": str(bundle),
        "model_bytes": model_bytes,
        "bundle_bytes": model_bytes + (bundle / "commands.json").stat().st_size,
        "load_ms": 1000 * (initialized - start),
        "first_ms": 1000 * (first - initialized),
        "warm_median_ms": median(times),
        "warm_p95_ms": quantiles(times, n=20, method="inclusive")[18],
        "warm_requests": len(times),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", type=Path, nargs="+")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    requests = [text for text, _, _ in examples("test") + manual_examples() + fresh_examples()]
    reference = None
    reports = []
    for bundle in args.bundles:
        decoded, report = run(bundle, requests, args.repetitions)
        if reference is None:
            reference = decoded
        report["commands_matching_first_bundle"] = sum(a == b for a, b in zip(reference, decoded))
        reports.append(report)
    print(json.dumps({"requests": len(requests), "bundles": reports}, indent=2))
