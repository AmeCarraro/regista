import numpy as np

from command_text import INTENTS, LABELS, LIMIT, decode, encode, read_slots


def test_command_tokens_keep_original_spelling_and_reject_overlong_text():
    text = "foto di Straße e Sa\u0303o"
    tokens, words = encode(text, {"strasse": 2})
    assert [word.group() for word in words] == ["foto", "di", "Straße", "e", "Sa", "\u0303", "o"]
    assert len(tokens) == LIMIT and tokens[2] == 2 and tokens[-1] == 0
    assert encode("foto " * (LIMIT + 1), {}) == ([], [])


def test_command_boundaries_use_only_the_slots_for_the_chosen_action():
    text = "riproduci Imagine di John Lennon"
    _, words = encode(text, {})
    choice = INTENTS.index("play_song")
    scores = np.full((1, LIMIT + 1, 6), -1.0)
    # The irrelevant tag overlaps the title. The title also includes the separator before the artist.
    scores[0, [1, 2, 1, 2, 3, 4], np.arange(6)] = 1
    (labels,) = read_slots(True, scores, [choice])
    assert labels[1] == LABELS.index("title")
    assert decode(text, words, INTENTS[choice], labels) == {
        "intent": "play_song", "slots": {"title": "Imagine", "artist": "John Lennon"},
    }

    scores[0, 3, 4] = -1
    scores[0, 2, 4] = 1  # Now the artist overlaps the title.
    (labels,) = read_slots(True, scores, [choice])
    assert decode(text, words, INTENTS[choice], labels) == {"intent": "clarify", "slots": {}}
