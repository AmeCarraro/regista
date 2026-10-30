"""The pictures of the library by kind: people, animals, landscapes, the city, food, documents, vehicles, sport,
things, screenshots. Worked out from the numbers the picture model already has of each picture, against sentences
that say each kind: no model is asked, and thousands of pictures take a moment.

Measured on the 200 samples and on a library of 3060 of the same ten kinds of Imagenette: 92.5% and 85% land in
their kind; when the first kind leads the second by MARGIN or more, as for about two pictures in three, 98.5% and
95%. Those are the sure ones, shown first; the others follow, as the less sure ones. A screenshot is known by its
name, not by what it shows: asked about screenshots, the picture model took a third of the library for them.
Nothing here moves a picture: the kinds are only a way of looking at the library, which stays as it is.
"""
import re
import threading
from pathlib import Path

import numpy as np

# each kind, its name on the page, and the things that show it, in the words the sentence model is given
KINDS = [
    ("persone", "Persone", ["persone", "il ritratto di una persona", "un selfie", "un gruppo di amici", "un bambino"]),
    ("animali", "Animali", ["un animale", "un cane", "un gatto", "un uccello", "un pesce", "un cavallo"]),
    ("natura", "Paesaggi e natura", ["un paesaggio", "le montagne", "il mare e la spiaggia", "un bosco", "un tramonto", "dei fiori"]),
    ("citta", "Città e monumenti", ["una strada di città", "un palazzo", "una chiesa", "un monumento", "una piazza"]),
    ("cibo", "Cibo", ["un piatto di cibo", "una pizza", "una torta", "un bicchiere di vino"]),
    ("documenti", "Documenti", ["un documento", "uno scontrino", "una pagina scritta", "un biglietto"]),
    ("veicoli", "Veicoli", ["un'automobile", "un camion", "una moto", "un treno", "un aereo", "una barca"]),
    ("sport", "Sport", ["una persona che fa sport", "una partita di calcio", "una pallina da golf", "un paracadute nel cielo"]),
    ("oggetti", "Oggetti", ["un oggetto", "un attrezzo", "uno strumento musicale", "un apparecchio elettronico"]),
]
SCREENSHOTS = ("schermate", "Schermate")
# a screenshot as phones and computers name it, or the folder they put it in
SCREENSHOT = re.compile(r"screen\s*shot|schermat[ae]|bildschirmfoto|captura", re.IGNORECASE)
# how far the first kind must lead the second for a picture to be sure of it
MARGIN = 0.01


class Kinds:
    """The kinds of a library's pictures, worked out again only when the library changed; each kind in `order`."""

    def __init__(self, embedder, order):
        self.embedder = embedder
        self.order = order
        self._sentences: np.ndarray | None = None
        self._made: tuple | None = None
        self._lock = threading.Lock()

    def _said(self) -> np.ndarray:
        """One row of numbers for each kind: the mean of its sentences, "una foto di …"."""
        if self._sentences is None:
            rows = []
            for _, _, things in KINDS:
                mean = np.stack([self.embedder.text(f"una foto di {thing}") for thing in things]).mean(axis=0)
                rows.append(mean / np.linalg.norm(mean))
            self._sentences = np.stack(rows)
        return self._sentences

    def sort(self, photos: list[dict], vectors: np.ndarray) -> dict[str, dict]:
        """{kind: {"label", "sure", "maybe"}}, every picture in one kind, each list in the order given (the newest first).

        A picture is {"id", "name", "day", "score"}, the score being how far its kind leads the next one.
        """
        with self._lock:
            key = (id(photos), id(vectors), len(photos))
            if self._made and self._made[0] == key:
                return self._made[1]
            sorted_out = {kind: {"label": label, "sure": [], "maybe": []} for kind, label, _ in [*KINDS, (*SCREENSHOTS, [])]}
            if photos and vectors.size:
                scores = vectors @ self._said().T
                order = np.argsort(-scores, axis=1)
                for at, photo in enumerate(photos):
                    first, second = order[at, 0], order[at, 1]
                    lead = float(scores[at, first] - scores[at, second])
                    entry = {"id": photo["id"], "name": Path(photo["path"]).name, "day": photo.get("day", ""), "score": round(lead, 4)}
                    if SCREENSHOT.search(photo["path"]):
                        sorted_out[SCREENSHOTS[0]]["sure"].append(entry)
                    else:
                        sorted_out[KINDS[first][0]]["sure" if lead >= MARGIN else "maybe"].append(entry)
            for group in sorted_out.values():
                group["sure"].sort(key=self.order)
                group["maybe"].sort(key=self.order)
            self._made = (key, sorted_out)
            return sorted_out


def in_words(sorted_out: dict[str, dict], total: int) -> str:
    """What the sorting found, said by the app: the numbers are counted here."""
    counted = sorted(((len(group["sure"]) + len(group["maybe"]), group["label"]) for group in sorted_out.values()), key=lambda kind: (-kind[0], kind[1]))
    listed = ", ".join(f"{label} {count}" for count, label in counted if count)
    if not listed:
        return "Non ho ancora foto da dividere per tipo: quando avrò letto la cartella, le troverai in «Foto», nel pannello a sinistra."
    return (f"Ho diviso per tipo {'la foto' if total == 1 else f'le {total} foto'}: {listed}. Le trovi in «Foto», nel pannello a sinistra, "
            "con una cartella per tipo e «Tutte». Non ho spostato niente: sul disco sono dove erano.")
