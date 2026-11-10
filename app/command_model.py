"""Run an exported Regista command model on the local CPU."""

from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort

from command_text import INTENTS, LABELS, LIMIT, decode, encode, read_slots


class CommandModel:
    def __init__(self, bundle: str | Path):
        bundle = Path(bundle)
        metadata = json.loads((bundle / "commands.json").read_text(encoding="utf-8"))
        payload = (bundle / "commands.onnx").read_bytes()
        if sha256(payload).hexdigest() != metadata.get("model_sha256"):
            raise ValueError("Il modello dei comandi non corrisponde ai suoi metadati.")
        if (metadata.get("format_version") != 1
                or metadata.get("intents") != list(INTENTS) or metadata.get("labels") != list(LABELS)
                or metadata.get("input") != {"name": "tokens", "type": "int64", "length": LIMIT}
                or metadata.get("outputs") != ["intent_logits", "slot_logits"]
                or metadata.get("slot_encoding") not in ("boundaries", "per_token")):
            raise ValueError("Formato del modello dei comandi non supportato.")
        self.vocabulary = metadata["tokenizer"]["vocabulary"]
        self.boundaries = metadata["slot_encoding"] == "boundaries"
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.runtime = ort.InferenceSession(payload, options, providers=["CPUExecutionProvider"])

    def ask(self, text: str) -> dict:
        tokens, words = encode(text, self.vocabulary)
        if not tokens:
            return {"intent": "clarify", "slots": {}}
        choices, scores = self.runtime.run(["intent_logits", "slot_logits"],
                                           {"tokens": np.asarray([tokens], dtype=np.int64)})
        choice = int(choices[0].argmax())
        labels = read_slots(self.boundaries, scores, [choice])[0]
        return decode(text, words, INTENTS[choice], labels)
