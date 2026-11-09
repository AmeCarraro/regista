"""Train and try Regista's small Italian command model, from random weights."""

import argparse
import json
from pathlib import Path
import re

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, TensorDataset

from commands_data import examples


INTENTS = ("search_photos", "add_tag", "remove_tag", "play_song", "clarify")
LABELS = ("O", "tag", "title", "artist")
WORDS = re.compile(r"\w+|[^\w\s]")
LIMIT = 64


class Commands(nn.Module):
    def __init__(self, vocabulary_size):
        super().__init__()
        self.words = nn.Embedding(vocabulary_size, 48, padding_idx=0)
        self.context = nn.ModuleList(
            nn.Conv1d(48, 48, 3, padding=distance, dilation=distance)
            for distance in (1, 2, 4, 8)
        )
        self.intent = nn.Linear(48, len(INTENTS))
        self.slots = nn.Linear(48, len(LABELS))

    def forward(self, tokens):
        present = tokens.ne(0)
        hidden = self.words(tokens).transpose(1, 2)
        for layer in self.context:
            hidden = (hidden + F.relu(layer(hidden))) * present.unsqueeze(1)
        hidden = hidden.transpose(1, 2)
        summary = hidden.masked_fill(~present.unsqueeze(-1), 0).amax(dim=1)
        return self.intent(summary), self.slots(hidden)


def encode(text, vocabulary):
    words = list(WORDS.finditer(text))
    if not words or len(words) > LIMIT:
        return [], []
    tokens = [vocabulary.get(word.group().casefold(), 1) for word in words]
    return tokens + [0] * (LIMIT - len(tokens)), words


def dataset(rows, vocabulary):
    tokens, intents, labels = [], [], []
    for text, intent, spans in rows:
        encoded, words = encode(text, vocabulary)
        if not encoded:
            raise ValueError(f"Invalid training command: {text!r}")
        tags = [0] * len(words)
        for slot, start, end in spans:
            selected = [i for i, word in enumerate(words) if start <= word.start() and word.end() <= end]
            if not selected or words[selected[0]].start() != start or words[selected[-1]].end() != end:
                raise ValueError(f"Unaligned {slot} in {text!r}")
            for i in selected:
                if tags[i] != 0:
                    raise ValueError(f"Overlapping slots in {text!r}")
                tags[i] = LABELS.index(slot)
        tokens.append(encoded)
        intents.append(INTENTS.index(intent))
        labels.append(tags + [-100] * (LIMIT - len(tags)))
    return TensorDataset(torch.tensor(tokens), torch.tensor(intents), torch.tensor(labels))


def decode(text, words, intent, labels):
    if intent == "clarify" or not words:
        return {"intent": "clarify", "slots": {}}
    slots = {}
    allowed = ("title", "artist") if intent == "play_song" else ("tag",)
    for name in allowed:
        indexes = [i for i, label in enumerate(labels[:len(words)]) if label == LABELS.index(name)]
        if indexes:
            first, last = indexes[0], indexes[-1]
            if len(indexes) != last - first + 1:
                return {"intent": "clarify", "slots": {}}
            # In «riproduci X di Y», the model can include the separator in X.
            if (name == "title" and first < last and last + 1 < len(words)
                    and labels[last + 1] == LABELS.index("artist")
                    and words[last].group().casefold() in {"di", "del", "della", "dei", "degli", "delle"}):
                last -= 1
            slots[name] = text[words[first].start():words[last].end()]
    if allowed[0] not in slots:
        return {"intent": "clarify", "slots": {}}
    return {"intent": intent, "slots": slots}


@torch.inference_mode()
def evaluate(model, data, rows, device):
    model.eval()
    intents, exact, wrong_edits = 0, 0, 0
    per_intent = {intent: {"exact": 0, "total": 0} for intent in INTENTS}
    offset = 0
    for tokens, _, _ in DataLoader(data, batch_size=128):
        predicted, labels = model(tokens.to(device))
        for choice, tags in zip(predicted.argmax(1).tolist(), labels.argmax(2).tolist()):
            text, intent, spans = rows[offset]
            words = list(WORDS.finditer(text))
            answer = decode(text, words, INTENTS[choice], tags)
            expected = {slot: text[start:end] for slot, start, end in spans}
            correct = answer == {"intent": intent, "slots": expected}
            exact += correct
            wrong_edits += not correct and answer["intent"] in ("add_tag", "remove_tag")
            intents += INTENTS[choice] == intent
            per_intent[intent]["exact"] += correct
            per_intent[intent]["total"] += 1
            offset += 1
    return {"examples": offset, "intent_accuracy": intents / offset, "exact_command": exact / offset,
            "incorrect_tag_edits": wrong_edits, "by_intent": per_intent}


def train(args):
    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA non disponibile. Controlla PyTorch con CUDA o usa --device cpu per una prova.")
    torch.manual_seed(args.seed)
    torch.set_num_threads(2)
    training, validation, test = (examples(split) for split in ("train", "validation", "test"))
    vocabulary = {word: i + 2 for i, word in enumerate(sorted({
        token.group().casefold() for text, _, _ in training for token in WORDS.finditer(text)
    }))}
    batches = DataLoader(dataset(training, vocabulary), batch_size=64, shuffle=True)
    validation_data, test_data = (dataset(rows, vocabulary) for rows in (validation, test))
    model = Commands(len(vocabulary) + 2).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002)
    best_score, best_epoch, best = -1, 0, None
    weights = torch.tensor([1.0, 2.0, 2.0, 2.0], device=args.device)
    hardware = torch.cuda.get_device_name() if args.device == "cuda" else "CPU"
    print(f"Device: {hardware} | Train: {len(training)}", flush=True)
    for epoch in range(1, args.epochs + 1):
        model.train()
        for tokens, intent, tags in batches:
            tokens, intent, tags = (value.to(args.device) for value in (tokens, intent, tags))
            # Replace some words with UNK so the model learns to extract names it has never seen.
            probability = torch.where(tags.gt(0), args.slot_dropout, 0.08)
            dropped = torch.rand(tokens.shape, device=args.device).lt(probability) & tokens.ne(0)
            choices, labels = model(tokens.masked_fill(dropped, 1))
            loss = F.cross_entropy(choices, intent) + F.cross_entropy(labels.transpose(1, 2), tags, weight=weights)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        score = evaluate(model, validation_data, validation, args.device)["exact_command"]
        print(f"Epoch {epoch:02d} | validation exact: {score:.1%}", flush=True)
        if score > best_score:
            best_score = score
            best_epoch = epoch
            best = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    model.load_state_dict(best)
    args.out.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out / "commands.pt"
    torch.save({"state": best, "vocabulary": vocabulary}, checkpoint)
    report = {"device": args.device, "hardware": hardware, "torch": str(torch.__version__),
              "seed": args.seed, "epochs": args.epochs, "best_epoch": best_epoch,
              "slot_dropout": args.slot_dropout, "training_examples": len(training),
              "parameters": sum(value.numel() for value in model.parameters()), "checkpoint_bytes": checkpoint.stat().st_size,
              "validation": evaluate(model, validation_data, validation, args.device),
              "test": evaluate(model, test_data, test, args.device)}
    (args.out / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


@torch.inference_mode()
def ask(args):
    model, vocabulary = load(args.out)
    for text in args.text:
        tokens, words = encode(text, vocabulary)
        if tokens:
            intent, slots = model(torch.tensor([tokens]))
            answer = decode(text, words, INTENTS[intent.argmax().item()], slots[0].argmax(1).tolist())
        else:
            answer = {"intent": "clarify", "slots": {}}
        print(json.dumps({"text": text, **answer}, ensure_ascii=False))


def load(out):
    saved = torch.load(out / "commands.pt", map_location="cpu", weights_only=True)
    vocabulary = saved["vocabulary"]
    model = Commands(len(vocabulary) + 2).eval()
    model.load_state_dict(saved["state"])
    return model, vocabulary


def benchmark(args):
    from commands_manual import examples as manual_examples

    torch.set_num_threads(2)
    model, vocabulary = load(args.out)
    rows = manual_examples()
    results = evaluate(model, dataset(rows, vocabulary), rows, "cpu")
    (args.out / "manual-metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/commands"))
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    training.add_argument("--epochs", type=int, default=20)
    training.add_argument("--seed", type=int, default=42)
    training.add_argument("--slot-dropout", type=float, default=0.55,
                          help="Probability of hiding a slot word during training")
    trying = commands.add_parser("ask")
    trying.add_argument("text", nargs="+")
    commands.add_parser("benchmark", help="Evaluate on independent handwritten requests")
    args = parser.parse_args()
    if args.command == "train":
        if args.epochs < 1:
            parser.error("--epochs must be positive")
        if not 0 <= args.slot_dropout <= 1:
            parser.error("--slot-dropout must be between 0 and 1")
        train(args)
    elif args.command == "ask":
        ask(args)
    else:
        benchmark(args)
