"""Train a small autoregressive Italian reply model from random weights."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, TensorDataset

from replies_data import examples


PAD, START, REPLY, END, UNKNOWN = range(5)
MAX_REPLY = 140
COUNT = "\ufff0"
ACTIONS = ("search", "add_tag", "remove_tag", "music_ambiguity", "clarify")


class Replies(nn.Module):
    def __init__(self, size, conditioned=False):
        super().__init__()
        self.characters = nn.Embedding(size, 32, padding_idx=PAD)
        self.action = nn.Embedding(len(ACTIONS) + 1, 16) if conditioned else None
        self.sequence = nn.GRU(48 if conditioned else 32, 64, batch_first=True)
        self.predict = nn.Linear(64, size)

    def forward(self, ids, actions, state=None):
        hidden = self.characters(ids)
        if self.action is not None:
            cue = self.action(actions).unsqueeze(1).expand(-1, ids.size(1), -1)
            hidden = torch.cat((hidden, cue), dim=2)
        output, state = self.sequence(hidden, state)
        return self.predict(output), state


def encode(text, vocabulary):
    return [vocabulary.get(character, UNKNOWN) for character in text]


def action_id(prompt):
    kind = prompt.partition("|")[0]
    return ACTIONS.index(kind) if kind in ACTIONS else len(ACTIONS)


def grounded_prompt(prompt):
    kind, _, fact = prompt.partition("|")
    if not fact.isdecimal():
        return prompt
    return f"{kind}|{'one' if fact == '1' else 'many'}"


def grounded_rows(rows):
    # Once the real count is removed, many rows become identical. Keep each wording once.
    return list(dict.fromkeys((grounded_prompt(prompt), re.sub(r"\d+", COUNT, reply)) for prompt, reply in rows))


def render_count(prompt, reply, ended):
    _, _, fact = prompt.partition("|")
    numeric = fact.isdecimal()
    if not ended or reply.count(COUNT) != int(numeric) or re.search(r"\d", reply):
        return "", False
    return reply.replace(COUNT, fact), True


def dataset(rows, vocabulary):
    inputs, targets = [], []
    for prompt, reply in rows:
        before = [START, *encode(prompt, vocabulary), REPLY]
        after = encode(reply, vocabulary) + [END]
        inputs.append(before + after[:-1])
        targets.append([-100] * (len(before) - 1) + after)
    width = max(map(len, inputs))
    padded = ([row + [PAD] * (width - len(row)) for row in inputs],
              [row + [-100] * (width - len(row)) for row in targets])
    return TensorDataset(*(torch.tensor(part) for part in padded),
                         torch.tensor([action_id(prompt) for prompt, _ in rows]))


@torch.inference_mode()
def generate(model, prompts, vocabulary, grounded=False):
    model.eval()
    device = next(model.parameters()).device
    inverse = {identifier: character for character, identifier in vocabulary.items()}
    by_length = defaultdict(list)
    for index, prompt in enumerate(prompts):
        encoded = [START, *encode(grounded_prompt(prompt) if grounded else prompt, vocabulary), REPLY]
        by_length[len(encoded)].append((index, encoded))
    result = [("", False)] * len(prompts)
    for group in by_length.values():
        ids = torch.tensor([tokens for _, tokens in group], device=device)
        actions = torch.tensor([action_id(prompts[index]) for index, _ in group], device=device)
        scores, state = model(ids, actions)
        generated = []
        finished = torch.zeros(len(group), device=device, dtype=torch.bool)
        for _ in range(MAX_REPLY):
            allowed = scores[:, -1, :].clone()
            allowed[:, [PAD, START, REPLY, UNKNOWN]] = -torch.inf
            next_ids = allowed.argmax(dim=1)
            generated.append(next_ids)
            finished |= next_ids.eq(END)
            if finished.all():
                break
            scores, state = model(next_ids.unsqueeze(1), actions, state)
        for (index, _), ids in zip(group, torch.stack(generated, dim=1).tolist()):
            ended = END in ids
            if ended:
                ids = ids[:ids.index(END)]
            reply = "".join(inverse[identifier] for identifier in ids)
            result[index] = render_count(prompts[index], reply, ended) if grounded else (reply, ended)
    return result


def evaluate(model, rows, vocabulary, grounded=False):
    prompts = list(dict.fromkeys(prompt for prompt, _ in rows))
    generated = generate(model, prompts, vocabulary, grounded)
    counted = correct = finished = 0
    by_kind = {}
    for prompt, (reply, ended) in zip(prompts, generated):
        kind, fact = prompt.split("|", 1)
        finished += ended
        if fact.isdecimal():
            counts = by_kind.setdefault(kind, {"exact": 0, "total": 0})
            exact = ended and re.findall(r"\d+", reply) == [fact]
            counted += 1
            correct += exact
            counts["exact"] += exact
            counts["total"] += 1
    return {"prompts": len(prompts), "finished": finished, "counts_exact": correct,
            "counts_total": counted, "by_kind": by_kind}


def train(args):
    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA non disponibile. Usa --device cpu per una prova locale.")
    torch.manual_seed(args.seed)
    torch.set_num_threads(2)
    training, validation, test = (examples(split) for split in ("train", "validation", "test"))
    train_rows = grounded_rows(training) if args.grounded else training
    validation_rows = grounded_rows(validation) if args.grounded else validation
    characters = sorted(set("".join(prompt + reply for prompt, reply in train_rows)))
    vocabulary = {character: i + UNKNOWN + 1 for i, character in enumerate(characters)}
    model = Replies(len(vocabulary) + UNKNOWN + 1, args.conditioned).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003)
    batches = DataLoader(dataset(train_rows, vocabulary), batch_size=16 if args.grounded else 64, shuffle=True)
    validation_inputs, validation_targets, validation_actions = (
        value.to(args.device) for value in dataset(validation_rows, vocabulary)[:]
    )
    best_loss, best_epoch, best = float("inf"), 0, None
    hardware = torch.cuda.get_device_name() if args.device == "cuda" else "CPU"
    print(f"Device: {hardware} | Train: {len(train_rows)}", flush=True)
    for epoch in range(1, args.epochs + 1):
        model.train()
        for ids, wanted, actions in batches:
            scores, _ = model(ids.to(args.device), actions.to(args.device))
            loss = F.cross_entropy(scores.transpose(1, 2), wanted.to(args.device))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            scores, _ = model(validation_inputs, validation_actions)
            loss = F.cross_entropy(scores.transpose(1, 2), validation_targets).item()
        if epoch == 1 or epoch % 5 == 0 or epoch == args.epochs:
            print(f"Epoch {epoch:02d} | validation loss: {loss:.3f}", flush=True)
        if loss < best_loss:
            best_loss, best_epoch = loss, epoch
            best = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}

    model.load_state_dict(best)
    args.out.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out / "replies.pt"
    torch.save({"state": best, "vocabulary": vocabulary, "grounded": args.grounded,
                "conditioned": args.conditioned}, checkpoint)
    report = {"device": hardware, "seed": args.seed, "epochs": args.epochs, "best_epoch": best_epoch,
              "training_examples": len(train_rows), "parameters": sum(value.numel() for value in model.parameters()),
              "checkpoint_bytes": checkpoint.stat().st_size, "grounded": args.grounded, "conditioned": args.conditioned,
              "validation": evaluate(model, validation, vocabulary, args.grounded),
              "test": evaluate(model, test, vocabulary, args.grounded)}
    (args.out / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


def ask(args):
    torch.set_num_threads(2)
    checkpoint = torch.load(args.out / "replies.pt", map_location="cpu", weights_only=True)
    vocabulary = checkpoint["vocabulary"]
    model = Replies(len(vocabulary) + UNKNOWN + 1, checkpoint.get("conditioned", False))
    model.load_state_dict(checkpoint["state"])
    for prompt, (reply, ended) in zip(args.prompt, generate(model, args.prompt, vocabulary, checkpoint.get("grounded", False))):
        print(json.dumps({"prompt": prompt, "reply": reply, "ended": ended}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/replies"))
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    training.add_argument("--epochs", type=int, default=30)
    training.add_argument("--seed", type=int, default=42)
    training.add_argument("--grounded", action="store_true", help="Insert verified counts into the generated text")
    training.add_argument("--conditioned", action="store_true", help="Give the model the selected action at each step")
    trying = commands.add_parser("ask")
    trying.add_argument("prompt", nargs="+")
    args = parser.parse_args()
    if args.command == "train":
        if args.epochs < 1:
            parser.error("--epochs must be positive")
        train(args)
    else:
        ask(args)
