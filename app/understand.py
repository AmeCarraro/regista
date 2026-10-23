"""What a request says the pictures should show, in the user's own words, read as the phone reads it (understand.ts).

The director turns a request into a short caption in English, and a small model can get a rare
word wrong: "mangianastri" once became "a bird feeder". So the user's own words are kept as
well, without the words around them ("trovami le foto di") and without what they say of the
period and of the place, which are read apart (period.py, places.py).
"""
import re

from period import MONTHS, SEASONS

# the words around what a request wants, which say nothing of the pictures
FILLER = set(
    (
        "foto fotografie fotografia immagini immagine scatti scatto trovami trova trovare trovatemi cerca cercami cercare mostrami mostra "
        "mostrare fammi fai vedere vedi dammi voglio vorrei tutte tutti tutta tutto mie miei mia mio ho hai fatto fatte fatta "
        "scattate scattata scattato scattati fotografato fotografata telefono telefonino tablet cellulare smartphone computer pc "
        "qui qua per favore grazie ciao ora adesso solo soltanto anche che cosa quali quale quelle quella quelli quello queste "
        "questa questi questo dove cui c è sono ci "
        "il lo la i gli le l un uno una di del dello della dei degli delle dell d a ad al allo alla ai agli alle all "
        "da dal dallo dalla dai dagli dalle dall in nel nello nella nei negli nelle nell con col su sul sullo sulla sui sugli "
        "sulle sull tra fra e ed o oppure non mi ti vi si me te "
        "find show me photo photos picture pictures image images of a an the with my all from on in"
    ).split()
)
# the words of a period, which period.py reads
TIME = set(MONTHS) | set(SEASONS) | set(
    "oggi ieri altro altroieri settimana scorsa scorso passata passato mese anno quest ultimi ultime giorni giorno settimane mesi anni".split()
)
_WORD = re.compile(r"[^\W\d_]+['’]?|\d+")


def own_words(asked: str, place: str = "") -> str:
    """What the pictures should show, as the request says it: "trovami una motosega" is "motosega".

    `place` is the name of the place the request was found to name, as written in it: its
    words come out, as the period's do. Empty when the request says nothing else.
    """
    found = list(_WORD.finditer(asked))
    named = {word.lower() for word in re.findall(r"[^\W\d_]+", place)}
    small = [match.group().lower().rstrip("'’") for match in found]
    # the words that say when or where: the request is cut there, into the parts that say what
    cut = [word in TIME or word.isdigit() or word in named for word in small]
    parts, start = [], 0
    for end in [*(index for index, out in enumerate(cut) if out), len(found)]:
        first, last = start, end - 1
        while first <= last and small[first] in FILLER:
            first += 1
        while last >= first and small[last] in FILLER:
            last -= 1
        if first <= last:
            parts.append(asked[found[first].start():found[last].end()])
        start = end + 1
    return " ".join(parts)
