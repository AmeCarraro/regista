"""Italian command examples with half-open character offsets into the original text."""

from random import Random
from string import Formatter


TEMPLATES = {
    "train": {
        "search_photos": (
            "mostrami foto {tag}", "trovami le foto con {tag}", "cerca le immagini con {tag}",
            "fammi vedere le foto di {tag}", "mi fai vedere le foto con {tag}?",
            "voglio vedere le immagini di {tag}", "quali foto hanno il tag {tag}?",
            "apri il catalogo {tag}", "cerca {tag} tra le foto", "mostra le foto etichettate {tag}",
            "cerca tutte le foto di {tag}", "hai delle fotografie con {tag}?",
            "dammi gli scatti con {tag}", "nella galleria cercami {tag}",
            "trova le fotografie che hanno {tag}", "puoi mostrarmi gli scatti con {tag}?",
            "fai vedere tutto quello che c'è nel catalogo {tag}", "mostrami quello che hai classificato {tag}",
            "mi fai sfogliare le foto con {tag}?", "mi cerchi qualche foto con {tag}?",
            "filtra la galleria per {tag}", "fammi vedere solo le foto con il tag {tag}",
            "{tag}, fammi vedere le foto", "dove sono le foto con il tag {tag}?",
            "mi tiri fuori qualche scatto con {tag}?", "puoi trovare le immagini in cui c'è {tag}?",
            "in galleria voglio solo le foto con {tag}", "quali scatti contengono {tag}?",
        ),
        "add_tag": (
            "metti {tag} su tutte queste foto", "aggiungi il tag {tag} alle foto selezionate",
            "etichetta queste immagini come {tag}", "segna tutti questi scatti come {tag}",
            "queste foto sono di {tag}, segnalo", "metti il tag {tag} sulle foto che ho scelto",
            "voglio aggiungere {tag} a queste foto", "sulle foto selezionate aggiungi {tag}",
            "classifica queste foto come {tag}", "raggruppa queste immagini sotto il tag {tag}",
            "assegna {tag} a tutte quelle selezionate", "etichetta con {tag} le foto che vedi",
            "a queste foto metti {tag}", "aggiungile al catalogo {tag}",
            "metti l'etichetta {tag} a tutte quelle che ho spuntato", "su tutte quelle lì scrivi {tag}",
            "vorrei assegnare il tag {tag} a tutti gli scatti", "per queste immagini usa il tag {tag}",
            "puoi applicare il tag {tag} alla mia selezione?", "dai a tutte queste foto il tag {tag}",
            "il tag da aggiungere a queste foto è {tag}", "segna queste fotografie con l'etichetta {tag}",
            "a quelle che ho selezionato associa {tag}", "su tutta la selezione aggiungi l'etichetta {tag}",
            "questi scatti vanno nel catalogo {tag}", "etichetta come {tag} le foto scelte",
            "a tutte le foto che ti ho indicato metti {tag}", "metti tutte queste nel gruppo {tag}",
            "ho scelto le immagini, adesso metti il tag {tag}", "{tag} è l'etichetta che voglio su queste foto",
        ),
        "remove_tag": (
            "togli {tag} da queste foto", "rimuovi il tag {tag} dalle foto selezionate",
            "elimina l'etichetta {tag} da tutti questi scatti", "queste foto non sono di {tag}, togli il tag",
            "dalle foto che ho scelto leva {tag}", "voglio togliere il tag {tag} a queste foto",
            "togli il tag {tag} da quelle selezionate", "rimuovi {tag} dalla selezione di foto",
            "togli dalle immagini l'etichetta {tag}", "deseleziona il tag {tag} sulle foto selezionate",
            "per queste foto elimina il tag {tag}", "leva l'etichetta {tag} da tutte queste immagini",
            "rimuovi dalle foto {tag}", "toglile dal catalogo {tag}",
            "elimina da questi scatti il tag {tag}", "queste immagini non devono più avere il tag {tag}",
            "il tag {tag} non va bene per queste foto, levalo", "su quelle che ho spuntato cancella il tag {tag}",
            "puoi togliere il tag {tag} alle immagini che ho scelto?", "le foto selezionate non devono avere {tag}",
            "su queste foto il tag {tag} non serve più", "il tag {tag} va rimosso da tutte quelle che ho scelto",
            "fammi il favore di togliere {tag} da questi scatti", "questo tag, {tag}, toglilo dalla selezione",
            "da tutte quelle qui rimuovi l'etichetta {tag}", "fai sparire da questi scatti il tag {tag}",
            "queste foto vanno tolte dal catalogo {tag}", "a tutte quelle che vedi leva il tag {tag}",
            "ho scelto gli scatti, adesso togligli il tag {tag}", "stacca l'etichetta {tag} dalle immagini selezionate",
            "togli {tag} alle foto, lasciale in galleria", "togli il tag {tag} alle foto che ti ho indicato",
        ),
        "play_song": (
            "riproduci {title} di {artist}", "fammi ascoltare {title} di {artist}",
            "metti la canzone {title} di {artist}", "voglio sentire {title} di {artist}",
            "tra i brani di {artist} suona {title}", "avvia il brano {title} di {artist}",
            "di {artist} fammi sentire {title}", "avvia {title}, il brano di {artist}",
            "suona {title}", "metti {title}", "riproducimi la canzone {title}",
            "fammi sentire il pezzo {title}", "fai partire {title}", "voglio ascoltare {title}",
            "metti {title}, la canzone di {artist}", "avvia la riproduzione di {title}",
            "ascoltiamo {title} cantata da {artist}", "mi metti {title} di {artist}?",
            "vorrei sentire la canzone {title}", "puoi mettere {title}?", "per la musica scegli {title}",
            "{title}, me la metti?", "mi fai ascoltare {title} di {artist}?", "fammi partire il pezzo {title}",
            "metti in riproduzione {title} di {artist}", "metti su {title}, il pezzo di {artist}",
            "ascoltiamo {artist}, metti {title}", "mi va di ascoltare {title} cantata da {artist}",
            'riproduci "{title}" di {artist}', "puoi suonare {title} del gruppo {artist}?",
        ),
    },
    "validation": {
        "search_photos": (
            "cercami le foto che mostrano {tag}", "mi servono gli scatti con {tag}",
            "sfoglia le immagini col tag {tag}", "trova in galleria le foto di {tag}",
            "foto di {tag}, me le fai vedere?",
        ),
        "add_tag": (
            "applica {tag} a tutte queste foto", "queste foto devono avere il tag {tag}",
            "marca con {tag} tutto quello che ho selezionato", "metti a questi scatti l'etichetta {tag}",
            "per tutte quelle che ho scelto imposta il tag {tag}",
        ),
        "remove_tag": (
            "cancella il tag {tag} dalle immagini evidenziate", "a queste foto leva l'etichetta {tag}",
            "il tag {tag} lo voglio rimuovere da questi scatti", "rimuovi da questa selezione l'etichetta {tag}",
            "puoi togliere alle foto il tag {tag}?",
        ),
        "play_song": (
            "mi fai sentire {title} di {artist}?", "metti il brano {title} che canta {artist}",
            "cerca {title} nella musica e falla partire", "parti con la canzone {title}",
            "voglio che riproduci {title} di {artist}",
        ),
    },
    "test": {
        "search_photos": (
            "ti va di mostrarmi le immagini con {tag}?", "fammi sfogliare il catalogo {tag}",
            "tira fuori le foto con l'etichetta {tag}", "mi mostri gli scatti di {tag}?",
            "voglio le foto che contengono {tag}",
        ),
        "add_tag": (
            "per tutte le foto che vedi scrivi {tag} come etichetta",
            "queste immagini etichettale {tag}", "a tutte le foto selezionate associa il tag {tag}",
            "fai sì che questi scatti abbiano tutti il tag {tag}", "segna come {tag} le foto spuntate",
        ),
        "remove_tag": (
            "vorrei levare da queste foto il tag {tag}", "per questi scatti cancella l'etichetta {tag}",
            "l'etichetta {tag} toglila alle immagini selezionate", "puoi rimuovere {tag} dalle foto scelte?",
            "in questa selezione il tag {tag} va tolto",
        ),
        "play_song": (
            "puoi far partire {title} di {artist}?", "vorrei ascoltare {title}, quella di {artist}",
            "dal catalogo musicale fammi ascoltare {title}", "fai suonare il brano {title}",
            "fammi partire la canzone {title} di {artist}",
        ),
    },
}

# Articles agree with the subject and stay outside the tag span.
PHOTO_ARTICLES = {
    "del ": ("mare", "Giappone", "lago", "tramonto", "bosco", "fiume", "ponte", "concerto", "cortile"),
    "dello ": ("stadio", "stagno", "zoo"),
    "della ": ("spiaggia", "Sardegna", "città", "neve", "montagna", "famiglia", "luna", "festa"),
    "dell'": ("Italia", "acquario", "alba", "aeroporto", "arcobaleno"),
    "dei ": ("cani", "gatti", "treni", "fiori", "tramonti", "documenti", "libri", "sentieri"),
    "degli ": ("uccelli", "animali", "alberi", "edifici", "scoiattoli"),
    "delle ": ("montagne", "persone", "Alpi", "auto rosse", "nuvole", "barche a vela", "finestre"),
}

PHOTO_ARTICLE_TEMPLATES = (
    "mostrami le foto {article}{tag}", "cerca le immagini {article}{tag}",
    "vorrei vedere le foto {article}{tag}", "mi trovi gli scatti {article}{tag}?",
    "dammi tutte le foto {article}{tag}", "voglio rivedere le foto {article}{tag}",
    "le foto {article}{tag}, fammele vedere", "hai delle foto {article}{tag}?",
)

TAGS = {
    "train": (
        "Giappone", "Italia", "Roma", "Sardegna", "Venezia", "Parigi", "Alpi", "mare", "cani",
        "cane nero", "gatti", "uccelli", "montagne", "tramonti", "documenti", "animali", "persone",
        "pranzo in famiglia", "Vacanze al mare", "Da stampare", "Foto per Marta", "Compleanno di Anna",
        "Ricette", "Natale", "Festa a sorpresa", "Da mandare a casa", "viaggio a Roma", "spiaggia",
        "auto rosse", "treni", "fiori", "ponti", "città", "sport", "lago", "foto mosse", "bici",
        "Da scegliere", "Scuola", "Estate 2025", "Album dei nonni", "Torre di Pisa", "Appunti",
        "Volti sorridenti", "Nord Italia", "Paesaggi", "Tessere e ricevute", "Ritratti",
    ),
    "validation": (
        "Islanda", "Colline verdi", "Cane bianco", "Pasqua", "Via dei Mille", "Ricordi con Nico",
        "Da mandare ad Arianna", "Scozia", "Dolomiti", "Primo giorno di scuola", "Aerei", "Boschi",
    ),
    "test": (
        "Viaggio in Giappone", "Da stampare per Luca", "Sicilia", "Corea del Sud", "fenicotteri",
        "Strade di notte", "Gita al lago", "Pagine del diario", "Barche", "Museo d'arte", "Neve e sole",
        "Gatti neri", "Da archiviare a dicembre", "Viaggio con Zia Carla", "scontrini", "mongolfiere",
    ),
}

# Invented names let the model practice copying novel text rather than relying on a music catalog.
SONGS = {
    "train": (
        ("Il cielo lento", "Neri d'Argento"), ("Briciole di luna", "Le Viole"),
        ("Tra i rami", "Milo Canepa"), ("Lettera per te", "Marta Belmonte"),
        ("Blu del mattino", "Tommaso Della Luna"), ("Mare da qui", "Riva Fredda"),
        ("La casa in collina", "Adele Rossi"), ("Noi due", "I Rami Alti"),
        ("Cose di carta", "Leo Foscari"), ("Fino a sera", "Nina Ferro"),
        ("Verso nord", "Isola Serena"), ("Ombra chiara", "Giorgio Costa"),
        ("Porta via la notte", "Piero Molino"), ("Quasi a casa", "Alba Fiorita"),
        ("Resta ancora", "Mia Vanelli"), ("Prima neve", "Vento Calmo"),
        ("In treno", "Elia del Rio"), ("Finestra sul porto", "Sara Antonelli"),
        ("Il mare senza rumore", "I Tre Passi"), ("Ventisette", "Luca Lari"),
        ("Dietro casa", "Leandro Pioli"), ("Notte d'agosto", "Anna Parini"),
        ("Scogli di rame", "Giulio Serra"), ("Con un passo", "Onde Unite"),
        ("Gocce di rame", "Sole Nuovo"), ("Giorni di carta", "Rosa Donati"),
        ("Ultima alba", "I Sette Vetri"), ("Sulla soglia", "Guido Venturi"),
        ("Vetro", "Nora Forte"), ("Passi leggeri", "Viola Sebastiani"),
        ("Fermati qui", "I Portici"), ("Tasche piene", "Camilla da Monte"),
        ("Paper Moons", "The Crane Family"), ("Blue on Blue", "May Winter"),
        ("A Quiet Song", "DJ Mare"), ("12 passi", "Il Trio"),
        ("Niente", "Giada"), ("Luci tra le case", "L'Officina"),
        ("Una porta chiusa", "Luna 27"), ("Sì o no", "Città Aperta"),
    ),
    "validation": (
        ("Luce oltre il muro", "Adele Negri"), ("I giorni del vento", "Vittorio Casati"),
        ("Tre righe blu", "Le Isole Bianche"), ("Vecchio giradischi", "Paolo Tramonte"),
        ("L'eco del fiume", "Tessa Leone"), ("Braci", "I Vicoli"),
        ("Foglie nel cassetto", "Angela Marini"), ("La memoria del sale", "Manuel Rota"),
    ),
    "test": (
        ("Un pezzo di cielo", "Emilia Volpi"), ("Cartoline da Torino", "Notti di Vetro"),
        ("Al di là del ponte", "Milo dei Sassi"), ("Pioggia d'estate", "Luna Lorenzi"),
        ("Nessuna fretta", "Rino Malvezzi"), ("Porte di Carta", "Asia D'Amico"),
        ("Fogli sparsi", "I Sassi Chiari"), ("In mezzo al mare", "Marco Arcieri"),
        ("Mercoledì", "Celeste Tonini"), ("Orizzonte blu", "Beatrice Fiorini"),
        ("Gira la ruota", "Carlo Vallesi"), ("Ultimo treno per casa", "Nadia Delle Rose"),
    ),
}

CLARIFY = {
    "train": (
        "mostrami le foto", "cerca una foto", "fammi vedere quelle", "mostra il catalogo",
        "trovami qualcosa", "cerca nella galleria", "dove sono le immagini?", "mi trovi delle foto?",
        "metti il tag", "mettilo su tutte", "metti quello su queste foto", "dagli un'etichetta",
        "etichetta tutto", "aggiungi un tag", "le ho selezionate, segnalo", "togli il tag",
        "rimuovi quell'etichetta", "levaglielo", "rimuovi tutte le etichette", "cancella queste foto",
        "togli il catalogo", "avvia una canzone", "fammi ascoltare qualcosa", "metti musica",
        "riproduci un brano", "voglio sentire una canzone", "puoi suonarla?", "vai al prossimo brano",
        "ciao", "che tempo fa?", "come stai?", "che ore sono?", "mi dai una mano?", "cosa puoi fare?",
        "mandami una foto", "scrivi una storia", "hai trovato qualcosa?", "non fare nulla",
        "aggiungi il tag {tag}", "rimuovi il tag {tag}", "che cos'è il tag {tag}?",
        "conosci la canzone {title}?", "chi canta {title}?",
        "togli queste dalla selezione", "togli tutte le foto", "cancella la foto che ho aperto",
        "leva il tag da qui", "non mettere nessun tag alle foto", "togli l'etichetta a tutte queste immagini",
        "annulla le modifiche", "vai alla galleria", "porta la musica al massimo", "salta questo pezzo",
        "aggiungi {title} ai preferiti", "chi ha scritto {title}?", "quando è uscita {title}?",
        "quante immagini hanno il tag {tag}?", "spedisci queste foto di {tag}",
        "togli le foto di {tag} dalla galleria", "crea un album che si chiama {tag}",
        "mostrami {tag} e poi metti la musica", "non togliere il tag {tag} da queste foto",
    ),
    "validation": (
        "fammi vedere una foto a caso", "non ricordo quale canzone volevo", "aggiungi il catalogo",
        "etichetta tutte quelle lì", "suona quella", "cosa vuol dire {tag}?", "sai chi canta {title}?",
        "aggiorna l'app", "apri la musica", "mi spieghi come si usa?", "sposta le foto di {tag}",
        "aspetta un momento", "scegli la musica tu", "voglio togliere un'etichetta", "voglio le foto",
        "dimentica il telefono", "segna quelle", "cambia le categorie",
    ),
    "test": (
        "ci sono foto nel catalogo?", "che canzone è {title}?", "alza il volume", "metti lo stesso tag",
        "manda a Luca le foto di {tag}", "togli il tag alle foto spuntate", "che giorno è oggi?",
        "riproduci quella di prima", "trovami il catalogo giusto", "mi fai una foto?", "crea un album",
        "dove trovo il tag {tag}?", "mi metti il solito brano?", "segna tutte quelle che ho scelto",
        "spegni la musica", "apri il telefono", "ricordi cosa ho chiesto?", "togli quell'etichetta",
    ),
}

_FORMATTER = Formatter()
_SEEDS = {"train": 46, "validation": 47, "test": 48}


def _fill(template, values, prefix="", suffix=""):
    text = prefix
    slots = []
    for literal, name, _, _ in _FORMATTER.parse(template):
        text += literal
        if name is not None:
            value = values[name]
            slots.append((name, len(text), len(text) + len(value)))
            text += value
    return text + suffix, slots


def _phrasing(rng, template, values):
    prefix = rng.choice(("", "", "", "Regista, ", "per favore ", "ehi, ", "senti, "))
    suffix = rng.choice(("", "", "", " per favore", ", grazie")) if not template.endswith("?") else ""
    # Simulate a speech recognizer that sometimes returns only lower case.
    if rng.random() < 0.4:
        values = {name: value.lower() for name, value in values.items()}
        prefix = prefix.lower()
    return _fill(template, values, prefix, suffix)


def examples(split: str) -> list[tuple[str, str, list[tuple[str, int, int]]]]:
    """Return deterministic examples with disjoint templates and slot values by split."""
    split = {"val": "validation", "dev": "validation"}.get(split, split)
    if split not in _SEEDS:
        raise ValueError(f"Unknown command split: {split!r}")
    rng = Random(_SEEDS[split])
    result = {}
    tags = [{"tag": tag} for tag in TAGS[split]]
    songs = [{"title": title, "artist": artist} for title, artist in SONGS[split]]
    for intent, templates in TEMPLATES[split].items():
        for template in templates:
            for values in songs if intent == "play_song" else tags:
                text, slots = _phrasing(rng, template, values)
                result[text] = (text, intent, slots)

    if split == "train":
        for article, subjects in PHOTO_ARTICLES.items():
            for template in PHOTO_ARTICLE_TEMPLATES:
                for tag in subjects:
                    text, slots = _phrasing(rng, template.replace("{article}", article), {"tag": tag})
                    result[text] = (text, "search_photos", slots)

    for template in CLARIFY[split]:
        if "{tag}" in template:
            values_to_use = tags
        elif "{title}" in template:
            values_to_use = songs
        else:
            values_to_use = [{}] * (6 if split == "train" else 3)
        for values in values_to_use:
            text, _ = _phrasing(rng, template, values)
            result[text] = (text, "clarify", [])

    rows = list(result.values())
    rng.shuffle(rows)
    return rows
