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
from commands_references import examples as reference_examples


INTENTS = ("search_photos", "add_tag", "remove_tag", "play_song", "clarify")
LABELS = ("O", "tag", "title", "artist")
EDITS = ("add_tag", "remove_tag")
WORDS = re.compile(r"\w+|[^\w\s]")
LIMIT = 64


class Commands(nn.Module):
    def __init__(self, vocabulary_size, boundaries=False):
        super().__init__()
        self.boundaries = boundaries
        self.words = nn.Embedding(vocabulary_size, 48, padding_idx=0)
        self.context = nn.ModuleList(
            nn.Conv1d(48, 48, 3, padding=distance, dilation=distance)
            for distance in (1, 2, 4, 8)
        )
        self.intent = nn.Linear(48, len(INTENTS))
        if boundaries:
            # One start and one end for each slot, plus a score for an absent slot.
            self.edges = nn.Linear(48, 2 * (len(LABELS) - 1))
            self.absent = nn.Linear(48, 2 * (len(LABELS) - 1))
        else:
            self.slots = nn.Linear(48, len(LABELS))

    def forward(self, tokens):
        present = tokens.ne(0)
        hidden = self.words(tokens).transpose(1, 2)
        for layer in self.context:
            hidden = (hidden + F.relu(layer(hidden))) * present.unsqueeze(1)
        hidden = hidden.transpose(1, 2)
        summary = hidden.masked_fill(~present.unsqueeze(-1), 0).amax(dim=1)
        if self.boundaries:
            edges = self.edges(hidden).masked_fill(~present.unsqueeze(-1), -1e4)
            spans = torch.cat((edges, self.absent(summary).unsqueeze(1)), dim=1)
            return self.intent(summary), spans
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


def edge_targets(tags):
    positions = torch.arange(LIMIT, device=tags.device)
    targets = []
    for slot in range(1, len(LABELS)):
        matches = tags.eq(slot)
        start = torch.where(matches, positions, LIMIT).amin(dim=1)
        end = torch.where(matches, positions, -1).amax(dim=1)
        targets.extend((start, torch.where(end < 0, LIMIT, end)))
    return torch.stack(targets, dim=1)


def read_slots(model, scores, choices):
    if not model.boundaries:
        return scores.argmax(2).tolist()
    sequences = []
    for choice, edges in zip(choices, scores.argmax(1).tolist()):
        tags = [0] * LIMIT
        intent = INTENTS[choice]
        relevant = {"play_song": (2, 3), "clarify": ()}.get(intent, (1,))
        for slot in relevant:
            start, end = edges[2 * (slot - 1):2 * slot]
            if start == end == LIMIT:
                continue
            if not 0 <= start <= end < LIMIT or any(tags[start:end + 1]):
                tags = [0] * LIMIT
                break
            tags[start:end + 1] = [slot] * (end - start + 1)
        sequences.append(tags)
    return sequences


def guarded_answer(text, words, intent, labels, confidence, edit_confidence):
    if intent in EDITS and confidence < edit_confidence:
        intent = "clarify"
    return decode(text, words, intent, labels)


@torch.inference_mode()
def evaluate(model, data, rows, device, edit_confidence=0):
    model.eval()
    intents, exact, wrong_edits, unexpected_actions = 0, 0, 0, 0
    per_intent = {intent: {"exact": 0, "total": 0} for intent in INTENTS}
    offset = 0
    for tokens, _, _ in DataLoader(data, batch_size=128):
        predicted, labels = model(tokens.to(device))
        confidence, choice_ids = predicted.softmax(1).max(1)
        choices = choice_ids.tolist()
        for choice, tags, certainty in zip(choices, read_slots(model, labels, choices), confidence.tolist()):
            text, intent, spans = rows[offset]
            words = list(WORDS.finditer(text))
            answer = guarded_answer(text, words, INTENTS[choice], tags, certainty, edit_confidence)
            expected = {slot: text[start:end] for slot, start, end in spans}
            correct = answer == {"intent": intent, "slots": expected}
            exact += correct
            wrong_edits += not correct and answer["intent"] in EDITS
            unexpected_actions += intent == "clarify" and answer["intent"] != "clarify"
            intents += INTENTS[choice] == intent
            per_intent[intent]["exact"] += correct
            per_intent[intent]["total"] += 1
            offset += 1
    return {"examples": offset, "intent_accuracy": intents / offset, "exact_command": exact / offset,
            "incorrect_tag_edits": wrong_edits, "unexpected_actions": unexpected_actions,
            "by_intent": per_intent}


def train(args):
    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA non disponibile. Controlla PyTorch con CUDA o usa --device cpu per una prova.")
    torch.manual_seed(args.seed)
    torch.set_num_threads(2)
    training, validation, test = (examples(split) for split in ("train", "validation", "test"))
    if args.references:
        training.extend(reference_examples())
    vocabulary = {word: i + 2 for i, word in enumerate(sorted({
        token.group().casefold() for text, _, _ in training for token in WORDS.finditer(text)
    }))}
    batches = DataLoader(dataset(training, vocabulary), batch_size=64, shuffle=True)
    validation_data, test_data = (dataset(rows, vocabulary) for rows in (validation, test))
    model = Commands(len(vocabulary) + 2, args.boundaries).to(args.device)
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
            slot_loss = (F.cross_entropy(labels, edge_targets(tags)) if args.boundaries
                         else F.cross_entropy(labels.transpose(1, 2), tags, weight=weights))
            loss = F.cross_entropy(choices, intent) + slot_loss
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
    torch.save({"state": best, "vocabulary": vocabulary, "boundaries": args.boundaries}, checkpoint)
    report = {"device": args.device, "hardware": hardware, "torch": str(torch.__version__),
              "seed": args.seed, "epochs": args.epochs, "best_epoch": best_epoch,
              "slot_dropout": args.slot_dropout, "boundaries": args.boundaries, "references": args.references,
              "training_examples": len(training),
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
            confidence, choice_id = intent.softmax(1).max(1)
            choice = choice_id.item()
            answer = guarded_answer(text, words, INTENTS[choice], read_slots(model, slots, [choice])[0],
                                    confidence.item(), args.edit_confidence)
        else:
            answer = {"intent": "clarify", "slots": {}}
        print(json.dumps({"text": text, **answer}, ensure_ascii=False))


def load(out):
    saved = torch.load(out / "commands.pt", map_location="cpu", weights_only=True)
    vocabulary = saved["vocabulary"]
    model = Commands(len(vocabulary) + 2, saved.get("boundaries", False)).eval()
    model.load_state_dict(saved["state"])
    return model, vocabulary


def benchmark(args):
    if args.suite == "fresh":
        from commands_fresh import examples as written_examples
    else:
        from commands_manual import examples as written_examples

    torch.set_num_threads(2)
    rows = written_examples()
    training_texts = {text.casefold() for text, _, _ in examples("train") + reference_examples()}
    for text, _, _ in rows:
        if text.casefold() in training_texts:
            raise ValueError(f"Benchmark overlaps with training: {text!r}")
    model, vocabulary = load(args.out)
    results = evaluate(model, dataset(rows, vocabulary), rows, "cpu", args.edit_confidence)
    results["edit_confidence"] = args.edit_confidence
    (args.out / f"{args.suite}-metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


def calibrate(args):
    torch.set_num_threads(2)
    model, vocabulary = load(args.out)
    rows = examples("validation")
    data = dataset(rows, vocabulary)
    trials = []
    for threshold in (0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98):
        result = evaluate(model, data, rows, "cpu", threshold)
        edits = sum(result["by_intent"][intent]["exact"] for intent in EDITS)
        trials.append({"threshold": threshold, "correct_edits": edits, **result})
    # Keep at least 90% of the correct edit proposals on validation.
    eligible = [trial for trial in trials if trial["correct_edits"] * 10 >= trials[0]["correct_edits"] * 9]
    chosen = min(eligible, key=lambda trial: (trial["incorrect_tag_edits"], -trial["exact_command"], trial["threshold"]))
    report = {"threshold": chosen["threshold"], "validation": trials}
    (args.out / "edit-calibration.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"without_guard": trials[0], "chosen": chosen}, indent=2))


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
    training.add_argument("--boundaries", action="store_true", help="Predict start and end positions for each slot")
    training.add_argument("--references", action="store_true", help="Add paraphrases for photo search and music")
    trying = commands.add_parser("ask")
    trying.add_argument("text", nargs="+")
    measuring = commands.add_parser("benchmark", help="Evaluate on independent handwritten requests")
    measuring.add_argument("--suite", choices=("manual", "fresh"), default="manual")
    for command in (trying, measuring):
        command.add_argument("--edit-confidence", type=float, default=0,
                             help="Ask for clarification below this intent score on tag edits")
    commands.add_parser("calibrate", help="Choose a tag edit threshold on synthetic validation only")
    args = parser.parse_args()
    if not 0 <= getattr(args, "edit_confidence", 0) <= 1:
        parser.error("--edit-confidence must be between 0 and 1")
    if args.command == "train":
        if args.epochs < 1:
            parser.error("--epochs must be positive")
        if not 0 <= args.slot_dropout <= 1:
            parser.error("--slot-dropout must be between 0 and 1")
        train(args)
    elif args.command == "ask":
        ask(args)
    elif args.command == "benchmark":
        benchmark(args)
    else:
        calibrate(args)
