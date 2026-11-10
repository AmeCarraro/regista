"""Export a command checkpoint to ONNX and verify it on ONNX Runtime's CPU."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from onnx import TensorProto, helper, numpy_helper

from commands import INTENTS, LABELS, LIMIT, WORDS, decode, encode, examples, load, read_slots
from commands_fresh import examples as fresh_examples
from commands_manual import examples as manual_examples


INPUT = "tokens"
OUTPUTS = ("intent_logits", "slot_logits")
OPSET = 17


def answers(model, outputs, texts, encoded):
    intents, slots = outputs
    choices = intents.argmax(1).tolist()
    tags = read_slots(model.boundaries, slots, choices)
    return [decode(text, words, INTENTS[choice], labels)
            for text, (_, words), choice, labels in zip(texts, encoded, choices, tags)]


def compact_weights(payload):
    model = onnx.load_model_from_string(payload)
    casts = []
    for weight in model.graph.initializer:
        if weight.data_type != TensorProto.FLOAT:
            continue
        name = weight.name
        reduced = numpy_helper.to_array(weight).astype(np.float16)
        weight.CopyFrom(numpy_helper.from_array(reduced, name + ".fp16"))
        casts.append(helper.make_node("Cast", [weight.name], [name], to=TensorProto.FLOAT))
    nodes = list(model.graph.node)
    del model.graph.node[:]
    model.graph.node.extend(casts + nodes)
    return model.SerializeToString()


def verify(model, vocabulary, payload, compact):
    onnx.checker.check_model(payload)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    runtime = ort.InferenceSession(payload, options, providers=["CPUExecutionProvider"])

    texts = [text for text, _, _ in examples("test") + manual_examples() + fresh_examples()]
    texts.append(" ".join(["foto"] * LIMIT))
    encoded = [encode(text, vocabulary) for text in texts]
    tokens = torch.tensor([ids for ids, _ in encoded], dtype=torch.int64)
    maximum_error = 0.0

    # Check single-command inference as well as a different batch size.
    for start, end in ((0, 1), (1, len(texts))):
        batch = tokens[start:end]
        expected = model(batch)
        actual = runtime.run(list(OUTPUTS), {INPUT: batch.numpy()})
        for left, right in zip(expected, actual):
            left = left.numpy()
            np.testing.assert_allclose(right, left, atol=0.02 if compact else 1e-4, rtol=1e-4, equal_nan=False)
            maximum_error = max(maximum_error, float(np.max(np.abs(right - left))))

        inputs = texts[start:end], encoded[start:end]
        actual_tensors = tuple(torch.from_numpy(scores) for scores in actual)
        if answers(model, expected, *inputs) != answers(model, actual_tensors, *inputs):
            raise ValueError("ONNX and PyTorch produced different commands")

    return {"examples": len(texts), "max_logit_error": maximum_error}


@torch.inference_mode()
def export(checkpoint, out, compact=False):
    torch.set_num_threads(2)
    model, vocabulary = load(checkpoint)
    sample, _ = encode("mostrami le foto dei cani", vocabulary)
    model_file = BytesIO()
    torch.onnx.export(
        model, (torch.tensor([sample], dtype=torch.int64),), model_file,
        input_names=[INPUT], output_names=list(OUTPUTS), opset_version=OPSET, dynamo=False,
        dynamic_axes={name: {0: "batch"} for name in (INPUT, *OUTPUTS)},
    )
    payload = model_file.getvalue()
    if compact:
        payload = compact_weights(payload)
    parity = verify(model, vocabulary, payload, compact)

    metadata = {
        "format_version": 1,
        "opset": OPSET,
        "model_sha256": sha256(payload).hexdigest(),
        "weights_type": "float16" if compact else "float32",
        "input": {"name": INPUT, "type": "int64", "length": LIMIT},
        "outputs": OUTPUTS,
        "tokenizer": {"pattern": WORDS.pattern, "normalization": "casefold", "padding_id": 0, "unknown_id": 1,
                      "vocabulary": vocabulary},
        "intents": INTENTS,
        "labels": LABELS,
        "slot_encoding": "boundaries" if model.boundaries else "per_token",
        "parity": parity,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "commands.onnx").write_bytes(payload)
    (out / "commands.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "onnx_bytes": len(payload), **parity}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path, help="Directory containing commands.pt")
    parser.add_argument("--out", type=Path, required=True, help="Directory for commands.onnx and commands.json")
    parser.add_argument("--compact", action="store_true", help="Store weights in float16 and run in float32")
    args = parser.parse_args()
    export(args.checkpoint, args.out, args.compact)
