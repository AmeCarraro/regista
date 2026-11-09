"""Training-only paraphrases for photo searches and song requests."""

from random import Random

from commands_data import _phrasing


# Invented names include connectors that also occur in command phrases.
TAGS = (
    "Ultima sera a Levanto", "Caffè del porto", "Ritratti per il laboratorio", "Voci di quartiere",
    "La via delle fontane", "Rifugio d'autunno", "Arrivo da Trieste", "Cartoline dal confine",
    "La mostra a Prato", "Da mettere in bacheca", "Fuori programma di sabato", "Via d'Acqua",
    "Gita per i colleghi", "L'inverno sui colli", "Dietro casa di Olga", "Scatti per il circolo",
    "La luce delle sette", "Il sentiero di Nino", "Mercati di primavera", "Pranzo al faro",
    "Barche d'argento", "Il parco dopo la pioggia", "Sotto il glicine", "Da mandare a Leila",
)

PHOTO_REQUESTS = (
    "mi recuperi dalla galleria gli scatti che ho chiamato {tag}?",
    "come ritrovo le foto che ho messo sotto {tag}? mostrami quelle",
    "andiamo a vedere le immagini segnate {tag}",
    "sfogliamo le foto archiviate come {tag}",
    'apri il gruppo di foto chiamato "{tag}" per me',
    "mi servono solo quelle che avevo catalogato sotto {tag}",
    "tirami fuori le immagini marcate con {tag} dalla galleria",
    "quelle con l'etichetta {tag} riesci a farmele vedere?",
    "per il momento fammi vedere le foto che portano il nome {tag}",
    "nella galleria vai alle immagini con l'etichetta {tag}",
    "dovrei avere degli scatti sotto {tag}, cercameli",
    "se ci sono delle foto segnate {tag}, me le fai vedere?",
    'voglio rivedere la selezione di foto "{tag}"',
    "fammi ritrovare in galleria il gruppo {tag}",
    "mostra sullo schermo quelle che avevo raccolto in {tag}",
    "sai dove sono le foto sotto il nome {tag}? fammele vedere",
)

SONGS = (
    ("Sulle ali di carta", "Lino dei Gelsi"), ("Prima che venga sera", "Mara d'Oliva"),
    ("Lettere dalla riva", "I Fiori del Vento"), ("Un giro di chiave", "Alma Torri"),
    ("La città di vetro", "Elio Di Brina"), ("Senza un'altra parola", "Le Sette Lune"),
    ("Dopo il mare", "Nadia dell'Orto"), ("C'è luce sotto i ponti", "Arturo Costa Verde"),
    ("I treni di passaggio", "La Banda del Lago"), ("Le ultime ore del giorno", "Berto d'Avena"),
    ("Stelle da contare", "Clara Marché"), ("Il tempo non fa rumore", "Luca Serpi"),
    ("Le porte della notte", "Dora Vélez"), ("A nord del fiume", "Ettore Della Seta"),
    ("Quattro passi di corsa", "Le Onde di Rame"), ("Mille strade di ritorno", "Adele di Prato"),
    ("Once by the River", "Alina O’Neill"), ("Cenere di primavera", "Tito De Marchi"),
    ("Nel buio di luglio", "Mino Val d'Orsa"), ("Un caffè per la pioggia", "Élodie Vallon"),
    ("Porte aperte d'estate", "Miro D’Angeli"), ("Prima di tornare", "Quelli del Cortile"),
    ("Notes from the Coast", "Ivan Béla"), ("Un vento tra le dita", "Dario e le Volpi"),
)

SONG_REQUESTS = (
    'cerca nella musica "{title}" di {artist} e suonala',
    "metti il pezzo di {artist} che si intitola {title}",
    "mi fai ascoltare il brano {title}, nella versione cantata da {artist}?",
    "fai partire {title}, l'incisione di {artist}",
    "tra i brani di {artist}, riproduci quello dal titolo {title}",
    "vorrei sentire {title} interpretata da {artist}",
    "c'è {title} di {artist} nella libreria? mettila",
    'suona "{title}", quella incisa da {artist}',
    "avvia dalla mia musica il pezzo {title}",
    "facciamo partire il brano intitolato {title}",
    'vorrei mettere la canzone "{title}"',
    "puoi suonarmi la traccia {title} un attimo?",
    "vai nella mia musica e riproduci {title} eseguita da {artist}",
    "di {artist} vorrei ascoltare il pezzo {title}",
    "prendi il brano {title} dalla libreria musicale e fallo partire",
    'per la prossima canzone metti "{title}" di {artist}',
)


def examples() -> list[tuple[str, str, list[tuple[str, int, int]]]]:
    """Return the supplemental commands with offsets into their original text."""
    rng = Random(95)
    rows = []
    for request in PHOTO_REQUESTS:
        for tag in TAGS:
            text, slots = _phrasing(rng, request, {"tag": tag})
            rows.append((text, "search_photos", slots))
    for request in SONG_REQUESTS:
        for title, artist in SONGS:
            text, slots = _phrasing(rng, request, {"title": title, "artist": artist})
            rows.append((text, "play_song", slots))
    rng.shuffle(rows)
    return rows
