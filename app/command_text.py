"""Shared text and output contract for the command model."""

import re


INTENTS = ("search_photos", "add_tag", "remove_tag", "play_song", "clarify")
LABELS = ("O", "tag", "title", "artist")
EDITS = ("add_tag", "remove_tag")
WORDS = re.compile(r"\w+|[^\w\s]")
LIMIT = 64


def encode(text, vocabulary):
    words = list(WORDS.finditer(text))
    if not words or len(words) > LIMIT:
        return [], []
    tokens = [vocabulary.get(word.group().casefold(), 1) for word in words]
    return tokens + [0] * (LIMIT - len(tokens)), words


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


def read_slots(boundaries, scores, choices):
    if not boundaries:
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
