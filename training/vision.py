"""Train a compact ten-class image tagger from random weights on CIFAR-10."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

import torch
from torch import nn
from torch.nn import functional as F


ARCHIVE_URL = "https://cave.cs.toronto.edu/kriz/cifar-10-binary.tar.gz"
ARCHIVE_MD5 = "c32a1d4ab5d03f1284b67883e8d87530"
CLASSES = ("airplane", "automobile", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck")
RECORDS_PER_BATCH = 10_000
RECORD_BYTES = 1 + 3 * 32 * 32


class PhotoTagger(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(3, 24, 3, padding=1, bias=False), nn.BatchNorm2d(24), nn.ReLU(),
            nn.Conv2d(24, 32, 3, stride=2, padding=1, bias=False), nn.BatchNorm2d(32), nn.ReLU(),
            nn.Conv2d(32, 48, 3, padding=1, bias=False), nn.BatchNorm2d(48), nn.ReLU(),
            nn.Conv2d(48, 64, 3, stride=2, padding=1, bias=False), nn.BatchNorm2d(64), nn.ReLU(),
            nn.Conv2d(64, 80, 3, padding=1, bias=False), nn.BatchNorm2d(80), nn.ReLU(),
            nn.Conv2d(80, 96, 3, stride=2, padding=1, bias=False), nn.BatchNorm2d(96), nn.ReLU(),
            nn.AdaptiveAvgPool2d((2, 2)), nn.Flatten(), nn.Linear(96 * 4, len(CLASSES)),
        )

    def forward(self, images):
        return self.layers(images)


def read_cifar(archive):
    if not archive.is_file():
        raise FileNotFoundError(f"CIFAR-10 not found at {archive}. Download the binary archive from {ARCHIVE_URL}")
    with archive.open("rb") as stream:
        md5 = hashlib.file_digest(stream, "md5").hexdigest()
    if md5 != ARCHIVE_MD5:
        raise ValueError(f"Unexpected MD5 for the official CIFAR-10 binary archive: {md5}")

    filenames = [f"data_batch_{i}.bin" for i in range(1, 6)] + ["test_batch.bin"]
    batches = []
    with tarfile.open(archive, mode="r:gz") as tar:
        for name in filenames:
            member = tar.getmember(f"cifar-10-batches-bin/{name}")
            if not member.isfile() or member.size != RECORDS_PER_BATCH * RECORD_BYTES:
                raise ValueError(f"Invalid CIFAR-10 batch: {name}")
            with tar.extractfile(member) as stream:
                data = torch.frombuffer(bytearray(stream.read()), dtype=torch.uint8)
            batches.append(data.reshape(RECORDS_PER_BATCH, RECORD_BYTES))
    training = torch.cat(batches[:5])
    return training, batches[-1]


def split_data(records, seed):
    """Reserve 500 images of each class from the official training set."""
    rng = torch.Generator().manual_seed(seed)
    training, validation = [], []
    for label in range(len(CLASSES)):
        same = records[:, 0].eq(label).nonzero().flatten()
        if len(same) != 5_000:
            raise ValueError(f"Unexpected training support for {CLASSES[label]}: {len(same)}")
        shuffled = same[torch.randperm(len(same), generator=rng)]
        validation.append(shuffled[:500])
        training.append(shuffled[500:])
    return records[torch.cat(training)], records[torch.cat(validation)]


def unpack(records, device):
    pixels = records[:, 1:].reshape(-1, 3, 32, 32).to(device, memory_format=torch.channels_last)
    return pixels, records[:, 0].to(device, dtype=torch.long)


def normalize(images):
    return images.float().div_(127.5).sub_(1.0)


def augment(images):
    flip = torch.rand(len(images), 1, 1, 1, device=images.device) < 0.5
    images = torch.where(flip, images.flip((-1,)), images)
    offset = torch.randint(0, 9, (2,), device="cpu").tolist()
    padded = F.pad(images, (4, 4, 4, 4), mode="reflect")
    y, x = offset
    return padded[:, :, y:y + 32, x:x + 32].contiguous(memory_format=torch.channels_last)


@torch.inference_mode()
def evaluate(model, data, batch_size):
    images, labels = data
    model.eval()
    size = len(CLASSES)
    matrix = torch.zeros((size * size,), dtype=torch.long, device=images.device)
    for pictures, truth in zip(images.split(batch_size), labels.split(batch_size)):
        prediction = model(normalize(pictures)).argmax(1)
        matrix += torch.bincount(truth * size + prediction, minlength=size * size)
    counts = matrix.reshape(size, size).cpu()
    correct = counts.diag()
    actual = counts.sum(1)
    predicted = counts.sum(0)
    per_class = {}
    for i, label in enumerate(CLASSES):
        per_class[label] = {
            "support": int(actual[i]),
            "precision": float(correct[i]) / int(predicted[i]) if predicted[i] else 0.0,
            "recall": float(correct[i]) / int(actual[i]) if actual[i] else 0.0,
        }
    return {"accuracy": int(correct.sum()) / len(labels), "examples": len(labels),
            "by_class": per_class, "confusion": counts.tolist()}


def train(args):
    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA non disponibile. Verifica l'installazione di PyTorch con CUDA.")
    torch.manual_seed(args.seed)
    torch.set_num_threads(2)
    device = torch.device(args.device)
    original_train, original_test = read_cifar(args.archive)
    train_set, validation = split_data(original_train, args.seed)
    train_images, train_labels = unpack(train_set, device)
    validation_data = unpack(validation, device)
    model = PhotoTagger().to(device, memory_format=torch.channels_last)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    scaler = torch.amp.GradScaler(device.type, enabled=device.type == "cuda")
    hardware = torch.cuda.get_device_name() if device.type == "cuda" else "CPU"
    print(f"Device: {hardware} | Train: {len(train_labels)} | Validation: {len(validation)}", flush=True)
    best_accuracy, best_epoch, best = -1.0, 0, None
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = torch.randperm(len(train_labels), device=device)
        for index in order.split(args.batch_size):
            images = augment(normalize(train_images[index]))
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
                loss = F.cross_entropy(model(images), train_labels[index])
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
        schedule.step()
        accuracy = evaluate(model, validation_data, args.batch_size)["accuracy"]
        print(f"Epoch {epoch:02d} | validation accuracy: {accuracy:.1%}", flush=True)
        if accuracy > best_accuracy:
            best_accuracy, best_epoch = accuracy, epoch
            best = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}

    model.load_state_dict(best)
    args.out.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out / "photo-tagger.pt"
    torch.save({"state": best, "classes": CLASSES}, checkpoint)
    report = {
        "dataset": "CIFAR-10 binary", "dataset_url": ARCHIVE_URL, "archive_md5": ARCHIVE_MD5,
        "class_order": CLASSES, "seed": args.seed, "epochs": args.epochs, "best_epoch": best_epoch,
        "device": args.device, "hardware": hardware, "torch": str(torch.__version__),
        "batch_size": args.batch_size, "training_examples": len(train_labels),
        "parameters": sum(value.numel() for value in model.parameters()),
        "checkpoint_bytes": checkpoint.stat().st_size,
        "validation": evaluate(model, validation_data, args.batch_size),
        "official_test": evaluate(model, unpack(original_test, device), args.batch_size),
    }
    (args.out / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    test = report["official_test"]
    print(f"Best epoch: {best_epoch} | test accuracy: {test['accuracy']:.1%}")
    for label in CLASSES:
        row = test["by_class"][label]
        print(f"{label:10} precision {row['precision']:.1%} | recall {row['recall']:.1%}")
    print(f"Parameters: {report['parameters']:,} | checkpoint: {report['checkpoint_bytes']:,} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("build/vision-data/cifar-10-binary.tar.gz"))
    parser.add_argument("--out", type=Path, default=Path("build/vision"))
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1:
        parser.error("--epochs and --batch-size must be positive")
    train(args)
