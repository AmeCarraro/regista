"""Short Italian replies grounded in structured facts supplied by Regista.

Every prompt has the form ``action|value``. The value is a decimal count
except for ``clarify``, where it is the name of the missing field. Counts
must occur verbatim exactly once in the reply. Tag operations are proposals
and ask the user to confirm. A prompt can have several valid replies within
one split, but no prompt is shared between splits.
"""

from random import Random


_REPLIES = {
    "search": {
        "train": (
            "Ho trovato {count} foto.",
            "La ricerca ha trovato {count} foto.",
            "Ho trovato {count} foto nella galleria.",
            "Questa ricerca ha restituito {count} foto.",
            "Per questa ricerca ho trovato {count} foto.",
            "Nella galleria risultano {count} foto per questa ricerca.",
        ),
        "validation": (
            "La ricerca nella galleria restituisce {count} foto.",
            "Per la tua richiesta risultano {count} foto.",
            "Nella galleria ho trovato {count} foto per te.",
        ),
        "test": (
            "Ci sono {count} foto che corrispondono alla ricerca.",
            "Il risultato della ricerca è di {count} foto.",
            "La galleria contiene {count} foto che rispondono alla tua richiesta.",
        ),
    },
    "add_tag": {
        "train": (
            "Aggiungo il tag a {count} foto. Confermi?",
            "Vuoi aggiungere il tag a {count} foto?",
            "Posso aggiungere il tag a {count} foto. Confermi?",
            "Ti propongo di aggiungere il tag a {count} foto. Va bene?",
            "Stai per aggiungere il tag a {count} foto. Confermi?",
            "Vuoi che assegni il tag a {count} foto?",
        ),
        "validation": (
            "Confermi di voler aggiungere il tag a {count} foto?",
            "Prima di aggiungere il tag a {count} foto mi serve il tuo sì.",
            "Vuoi applicare il tag a {count} foto?",
        ),
        "test": (
            "Mi dai conferma per aggiungere il tag a {count} foto?",
            "La modifica proposta aggiunge il tag a {count} foto. Procedo?",
            "Posso assegnare questo tag a {count} foto. Va bene?",
        ),
    },
    "remove_tag": {
        "train": (
            "Tolgo il tag da {count} foto. Confermi?",
            "Vuoi rimuovere il tag da {count} foto?",
            "Posso togliere il tag da {count} foto. Confermi?",
            "Ti propongo di togliere il tag da {count} foto. Va bene?",
            "Stai per rimuovere il tag da {count} foto. Confermi?",
            "Vuoi che tolga il tag da {count} foto?",
        ),
        "validation": (
            "Confermi di voler rimuovere il tag da {count} foto?",
            "Prima di togliere il tag da {count} foto mi serve il tuo sì.",
            "Vuoi eliminare questo tag da {count} foto?",
        ),
        "test": (
            "Mi dai conferma per togliere il tag da {count} foto?",
            "La modifica proposta rimuove il tag da {count} foto. Procedo?",
            "Posso rimuovere questo tag da {count} foto. Va bene?",
        ),
    },
    "music_ambiguity": {
        "train": (
            "Ho trovato {count} brani. Quale vuoi ascoltare?",
            "Ci sono {count} brani con questo titolo. Di quale artista?",
            "Ho trovato {count} corrispondenze. Quale brano intendevi?",
            "La ricerca musicale ha trovato {count} brani. Quale preferisci?",
            "Ci sono {count} brani possibili. Mi dici l'artista?",
            "Vedo {count} brani che corrispondono. Quale faccio partire?",
        ),
        "validation": (
            "Ho trovato {count} brani compatibili. Sai dirmi l'artista?",
            "Ci sono {count} risultati per questo brano. Quale vuoi sentire?",
            "La libreria contiene {count} brani con quel titolo. Quale intendi?",
        ),
        "test": (
            "Tra i {count} brani trovati, quale ti interessa?",
            "Ho trovato {count} brani possibili. Di chi è quello che cerchi?",
            "Per quel titolo ho {count} risultati. Quale devo riprodurre?",
        ),
    },
}

_CLARIFICATIONS = {
    "train": {
        "tag": ("Quale tag intendi?", "Mi dici il nome del tag?", "Che tag devo usare?"),
        "photos": ("Quali foto intendi?", "Mi indichi le foto?", "A quali foto ti riferisci?"),
        "title": ("Quale brano vuoi ascoltare?", "Mi dici il titolo del brano?", "Che canzone intendi?"),
        "artist": ("Di quale artista?", "Quale artista intendi?", "Sai dirmi il nome dell'artista?"),
    },
    "validation": {
        "date": ("Quale data intendi?", "Di quale giorno sono le foto?"),
        "place": ("Quale luogo intendi?", "In che posto sono state scattate?"),
    },
    "test": {
        "device": ("Su quale dispositivo vuoi cercare?", "Quale dispositivo intendi?"),
        "album": ("Quale album intendi?", "Mi dici il nome dell'album?"),
    },
}

_SEEDS = {"train": 806, "validation": 807, "test": 808}


def examples(split: str) -> list[tuple[str, str]]:
    """Return deterministic prompt/reply rows with counts held out per action."""
    if split not in _SEEDS:
        raise ValueError(f"Unknown reply split: {split!r}")

    rows = []
    for offset, (action, templates) in enumerate(_REPLIES.items()):
        # Stagger the held-out values, so a count tested for one action can
        # still be seen for another. Music ambiguity needs at least two hits.
        counts = range(2, 27) if action == "music_ambiguity" else range(140)
        for count in counts:
            bucket = (count + 2 * offset) % 10
            count_split = {8: "validation", 9: "test"}.get(bucket, "train")
            if count_split == split:
                rows.extend((f"{action}|{count}", text.format(count=count)) for text in templates[split])

    for field, replies in _CLARIFICATIONS[split].items():
        rows.extend((f"clarify|{field}", reply) for reply in replies)

    Random(_SEEDS[split]).shuffle(rows)
    return rows
