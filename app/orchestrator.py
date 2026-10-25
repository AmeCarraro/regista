"""The orchestrator: reads a request, decides what to do with it, and does it.

It works in two moves. First one model, the "director", decides: answer in words,
search the pictures, count them, throw some away, copy some, take a change back.
It must reply with a small form, not with free text, so the decision is always one the
app can carry out. Then the app acts, and says what happened from what happened: the
numbers in a reply are counted by the app and never written by a model.

A model never changes a picture. A request to throw away, copy or undo becomes a
proposal: the page shows it, and it is carried out only when the user says yes there
(main.py). So a wrong decision costs a click on "no", and nothing else. Pictures on a
phone are thrown away by the phone, into its own trash, after a copy has arrived here
and after a second yes, given on the phone to Android itself.

The decision is a form, with examples, because a small model left free to call tools
calls them too often: asked for advice on taking pictures, it searched the pictures.
"""
import asyncio
import functools
import heapq
import json
import logging
import re
import time

import catalog
import llm
from actions import READ_ONLY, Refused, collection_name
from period import in_words as period_in_words
from period import read as read_period
from period import without_time
from phone import on_phone
from photos import LOOK_MOST, LOOK_STOP, SURE, for_the_eyes, newest
from places import IN_COUNTRY, REGIONS
from understand import own_words

logger = logging.getLogger("uvicorn.error")

ACTIONS = ("answer", "find_photos", "count_photos", "trash_photos", "copy_photos", "move_photos", "undo")
# the decisions that would change the pictures: they are proposed, never carried out here
CHANGES = ("trash_photos", "copy_photos", "move_photos", "undo")

# A request is about the pictures of the phone when it names the phone as a place: "sul telefono",
# "dal mio cellulare". This is read here, in the words of the user, and not asked to the model:
# the model has enough to decide already. "Una foto con un telefono" is a picture of a phone, not this.
ON_PHONE = re.compile(
    r"\b(?:dal|sul|nel|del|al)\s+(?:mio\s+)?(?:telefono|telefonino|cellulare|smartphone|tablet)\b"
    r"|\b(?:on|from|in)\s+(?:my|the)\s+(?:phone|smartphone|tablet)\b",
    re.IGNORECASE,
)
# Where pictures go, when it is the phone: "mandale sul telefono", "copia sul tablet le foto del mare".
# Then they come from the computer, unless the request also says they come from the phone.
TO_PHONE = re.compile(
    r"\b(?:sul|nel|al)\s+(?:mio\s+)?(?:telefono|telefonino|cellulare|smartphone|tablet)\b|\b(?:on|onto|to)\s+(?:my|the)\s+(?:phone|smartphone|tablet)\b",
    re.IGNORECASE,
)
# A verb that moves pictures: with the phone as where they go, the request is to send them there, whatever
# the model made of it. "Mettimi sul telefono le foto di Parigi" is sometimes taken for a search.
SENDS = re.compile(r"\b(?:mand|mett|copi|salv|trasferisc|trasferi|port|caric|invi)\w*", re.IGNORECASE)
FROM_PHONE = re.compile(r"\b(?:dal|dalla)\s+(?:mio\s+|mia\s+)?(?:telefono|telefonino|cellulare|smartphone|tablet)\b|\bfrom\s+(?:my|the)\s+(?:phone|smartphone|tablet)\b", re.IGNORECASE)
ON_COMPUTER = re.compile(r"\b(?:dal|sul|nel|del|al)\s+(?:mio\s+)?(?:computer|pc)\b|\b(?:on|from|in)\s+(?:my|the)\s+(?:computer|pc)\b", re.IGNORECASE)
# A request about copies of the same picture, "trovami le foto doppie", "elimina i doppioni"; and one for
# an album for each trip, "fammi gli album dei viaggi". Read here, in the words of the user: no model is
# needed to know them, and what follows is worked out by the app (photos.twins, trips.py).
TWINS = re.compile(r"\b(?:doppioni|doppie|duplicat[ei]|duplicates?|(?:foto|copie|immagini)\s+(?:uguali|identiche|ripetute))\b", re.IGNORECASE)
ALBUMS = re.compile(
    r"\balbum\w*\b[^.?!]*\bviagg|\bviagg\w*\b[^.?!]*\balbum"
    r"|\b(?:organizz|divid|raggrupp|smist|ordin|metti|separ)\w*\b[^.?!]*\bper\s+(?:ogni\s+)?viagg"
    r"|\btrip\s+albums?\b",
    re.IGNORECASE,
)
# A request that plainly asks to see pictures, and says so: "trovami le foto con una motosega", "le foto di
# un mangianastri". A small model sometimes takes one for a question and answers it; it is a search all the
# same. Not "mostrami un esempio", which names no pictures, nor "le foto sono belle", nor a question on how
# to do something: "come si cercano le foto?".
FIND = re.compile(
    r"^\W*(?:(?:ehi|ciao|dai|per favore)\W+)?(?:(?:trov|cerc|mostr)\w*|fammi\s+vedere|fai\s+vedere|voglio\s+vedere|vorrei\s+vedere)\b"
    r".*\b(?:foto|fotografie|immagini|scatti)\b"
    r"|^\W*(?:(?:tutte|solo)\s+)?(?:le\s+|delle\s+)?(?:mie\s+)?(?:foto|fotografie|immagini|scatti)\s+"
    r"(?:di|del|dello|della|dei|degli|delle|dell['’]|d['’]|con|col|coi|da|dal|dalla|in|nel|nella|a|al|alla|sul|sulla)\b",
    re.IGNORECASE,
)
HOW = re.compile(r"\b(?:come|perch[eé]|consigl\w*|spieg\w*|cos['’]\s*[eè]|cosa\s+(?:significa|vuol)|how|why)\b", re.IGNORECASE)
# what a model may leave in a caption about the place, and that the pictures do not show
PLACE_WORDS = re.compile(r"\b(?:on|onto|to|from|in|of)\s+(?:my\s+|the\s+)?(?:phone|smartphone|cellphone|mobile|tablet|computer|pc)\b", re.IGNORECASE)

DECIDE = (
    "You decide what an assistant must do with the last message of the user. "
    "Reply with the form only.\n"
    "- find_photos: the user wants to SEE or FIND pictures they own. "
    "caption says what the pictures show, as a short caption in English: translate it. "
    "When the user narrows down the last search, give the complete caption.\n"
    "- count_photos: the user asks how many pictures there are.\n"
    "- trash_photos: the user tells you to delete, remove or throw away pictures they own. "
    "caption says which pictures, in English, when the message says it; "
    "leave it empty when the user means the pictures just found ('these', 'them', 'le', 'quelle').\n"
    "- copy_photos: the user tells you to copy, save or put pictures into a folder. "
    "folder is the name the user gives to the folder, as written; caption as for trash_photos.\n"
    "- move_photos: the user tells you to move pictures into a folder ('sposta', 'spostale'): they leave the place "
    "where they are. folder and caption as for copy_photos.\n"
    "- undo: the user tells you to take back the last change: bring back what was deleted, cancel the copy.\n"
    "- answer: everything else. Greetings, thanks, questions, requests for advice or explanations, "
    "also when they are about photography, cameras, files, or HOW to delete or copy something.\n"
    "Leave caption and folder empty when they are not needed. "
    "The caption says what the pictures show, never where they are kept or when they were taken: "
    "no 'phone', 'computer', months, years or dates in it. When the message only says a period of time, the caption is empty.\n"
    "Examples:\n"
    'mostrami le foto della montagna -> {"action": "find_photos", "caption": "a mountain", "folder": ""}\n'
    'solo quelle con la neve (after a search for "a mountain") -> {"action": "find_photos", "caption": "a mountain with snow", "folder": ""}\n'
    'hai delle immagini di bambini che giocano? -> {"action": "find_photos", "caption": "children playing", "folder": ""}\n'
    'trovami una bicicletta -> {"action": "find_photos", "caption": "a bicycle", "folder": ""}\n'
    'trovami una ricetta per la torta di mele -> {"action": "answer", "caption": "", "folder": ""}\n'
    'come faccio a fotografare la luna? -> {"action": "answer", "caption": "", "folder": ""}\n'
    'quale obiettivo mi consigli per i ritratti? -> {"action": "answer", "caption": "", "folder": ""}\n'
    'perfetto, grazie -> {"action": "answer", "caption": "", "folder": ""}\n'
    'quante immagini ci sono? -> {"action": "count_photos", "caption": "", "folder": ""}\n'
    'eliminale -> {"action": "trash_photos", "caption": "", "folder": ""}\n'
    'butta via le foto dei tramonti -> {"action": "trash_photos", "caption": "a sunset", "folder": ""}\n'
    'mettile in una cartella chiamata Vacanze -> {"action": "copy_photos", "caption": "", "folder": "Vacanze"}\n'
    'salva le foto dei fiori nella cartella Giardino -> {"action": "copy_photos", "caption": "flowers", "folder": "Giardino"}\n'
    'sposta le foto del mare nella cartella Mare -> {"action": "move_photos", "caption": "the sea", "folder": "Mare"}\n'
    'spostale in una cartella che si chiama Vacanze -> {"action": "move_photos", "caption": "", "folder": "Vacanze"}\n'
    'prendi tutte le foto di Parigi e mettimele in una cartella Parigi -> {"action": "copy_photos", "caption": "Paris", "folder": "Parigi"}\n'
    'trovami sul telefono le foto del lago -> {"action": "find_photos", "caption": "a lake", "folder": ""}\n'
    'trovami le foto dal 20 maggio al 20 luglio -> {"action": "find_photos", "caption": "", "folder": ""}\n'
    'le foto del mare di agosto 2024 -> {"action": "find_photos", "caption": "the sea", "folder": ""}\n'
    'prendi dal telefono le foto della neve e salvale sul computer nella cartella Neve -> {"action": "copy_photos", "caption": "snow", "folder": "Neve"}\n'
    'mandami sul telefono le foto del mare -> {"action": "copy_photos", "caption": "the sea", "folder": ""}\n'
    'ripensandoci, rimettile dove erano -> {"action": "undo", "caption": "", "folder": ""}\n'
    'elimina dal telefono le foto dei tramonti -> {"action": "trash_photos", "caption": "a sunset", "folder": ""}\n'
    'come si elimina una foto dal telefono? -> {"action": "answer", "caption": "", "folder": ""}'
)
DECISION = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "caption": {"type": "string"},
        "folder": {"type": "string"},
    },
    "required": ["action", "caption", "folder"],
}

TALK = (
    "You are Regista, a personal assistant that runs on the user's own computer. "
    "Answer directly and briefly, in the language the user writes in. "
    "You cannot open, change or delete anything yourself: never say that you did."
)

# the conversation sent to the model: enough to follow a request that refers to the previous one
HISTORY = 12
# a decision is a few words
DECISION_TOKENS = 80
# how many pictures one request may propose to change: enough for a trip, few enough to look at them
MOST = 300
# the most pictures of a phone an answer for its own screen names
PHONE_SHOWN = 120
# the most pictures an answer shows when the request asks for all those of a period or of a place, the newest first;
# their small copies are loaded only as the page comes to them
EVERY = 3000

NO_MODEL = "Non trovo nessun modello locale. Controlla che Ollama sia acceso e che ci sia almeno un modello installato."
NO_PHOTOS = "Non ho ancora nessuna foto in cui cercare: metti delle foto nella cartella che mi hai indicato."
UNCLEAR = "Non ho capito cosa cercare nelle foto. Prova a dirmelo con altre parole."
WHICH_ONES = "Dimmi prima quali foto: cercale, e poi dimmi cosa farne."
NONE_LIKE_THAT = "Non ho trovato foto così, quindi non tocco niente."
NOTHING_TO_UNDO = "Non c'è niente da annullare: non ho ancora spostato né copiato nulla."
NO_PHONE = "Non c'è nessun telefono collegato. Collegane uno dal pannello, alla voce «Telefono»."
PHONE_EMPTY = "Il telefono è collegato, ma non mi ha ancora mandato le sue foto: apri Regista sul telefono e lascialo finire."
# where the copies of pictures taken off a phone are kept, among the collections
REMOVED = "Tolte dal telefono"
# the album on the phone for pictures of the computer, and the folder here for pictures a phone sends by itself
FROM_COMPUTER = "Dal computer"
FROM_THE_PHONE = "Dal telefono"
ALREADY_THERE = "Quelle foto sono già sul telefono."


def _photos(count: int) -> str:
    return "1 foto" if count == 1 else f"{count} foto"


def found_in_words(result: dict, phone: bool = False, when: str = "", described: bool = True) -> str:
    """What a search found, said by the app. The numbers are counted here, never written by a model.

    `when` is the period the request named, in words; `described` says whether it also
    said what the pictures show, or only when they were taken.
    """
    sure, maybe = len(result["sure"]), len(result["maybe"])
    every = result.get("matching", sure)
    where = (" sul telefono" if phone else "") + (f" {when}" if when else "")
    if not result["indexed"]:
        return PHONE_EMPTY if phone else NO_PHOTOS
    if every > sure:
        shown = "più vicine a quello che hai chiesto" if described else "più recenti"
        text = f"Ho trovato {_photos(every)}{where}: ti mostro le {sure} {shown}."
    elif sure:
        text = f"Ho trovato {_photos(sure)}{where}."
        if maybe:
            text += " Ce n'è un'altra che potrebbe andare bene." if maybe == 1 else f" Altre {maybe} potrebbero andare bene, ma ne sono meno sicuro."
    elif maybe:
        text = f"Non sono sicuro di averne trovate{where}. " + ("Questa è la più vicina." if maybe == 1 else f"Queste {maybe} sono le più vicine.")
    else:
        nothing = "niente del genere" if described else "foto"
        text = f"Non ho trovato {nothing}{f' {when}' if when else ''} tra le {result['indexed']} foto{' del telefono' if phone else ''} che conosco."
    if result.get("partial"):
        text += " Sto ancora leggendo le foto, quindi il risultato è parziale."
    return text


def counted_in_words(state: dict, indexed: int) -> str:
    """How many pictures the app knows, said by the app."""
    if state["running"]:
        return f"Sto ancora leggendo le foto: ne conosco {indexed} su {state['total']}."
    if not indexed:
        return NO_PHOTOS
    return f"Conosco {_photos(indexed)}."


def proposed_in_words(kind: str, count: int, folder: str, every: int = 0) -> str:
    """The question the user must answer before anything changes."""
    these = "questa foto" if count == 1 else f"queste {count} foto"
    into = f"nella cartella «{folder}»?" if folder else "in una cartella nuova? Scrivi qui sotto come chiamarla."
    if kind == "trash":
        text = f"Sposto nel cestino {these}? Restano sul disco, e le riporto dov'erano quando vuoi."
    elif kind == "fetch":
        text = f"Copio dal telefono al computer {these}, {into} Sul telefono restano dove sono."
    elif kind == "send":
        text = f"Mando sul telefono {these}, nell'album «{folder}»? Sul computer restano dove sono."
    elif kind == "move":
        text = f"Sposto {these} {into} Lasciano il posto dove sono: con «annulla» tornano dov'erano."
    elif kind == "clear":
        text = (f"Tolgo dal telefono {these}? Prima le copio sul computer, nella cartella «{folder}», e controllo che siano arrivate intere. "
                "Poi il telefono le sposta nel suo cestino, dove restano 30 giorni: te lo chiederà Android.")
    else:
        text = f"Copio {these} {into} Gli originali restano dove sono."
    if every > count:
        text += f" In tutto sono {every}: te ne propongo {count} per volta."
    return text


def undo_proposed_in_words(entry: dict) -> str:
    """The question before a change is taken back."""
    count = len(entry["files"])
    if entry["kind"] == "trash":
        back = "La rimetto al suo posto?" if count == 1 else "Le rimetto al loro posto?"
        return f"L'ultima modifica è stata spostare {_photos(count)} nel cestino. {back}"
    if entry["kind"] == "move":
        back = "La rimetto dov'era?" if count == 1 else "Le rimetto dov'erano?"
        return f"L'ultima modifica è stata spostare {_photos(count)} nella cartella «{entry.get('folder', '')}». {back}"
    copies = "quella copia" if count == 1 else "quelle copie"
    if entry["kind"] == "receive" and entry.get("cleared"):
        # the pictures left the phone: what can be taken back from here is only the copy, and the user must know
        return (f"L'ultima modifica è stata togliere {_photos(entry['cleared'])} dal telefono, dopo averle copiate nella cartella «{entry.get('folder', '')}». "
                "Sul telefono le riprendi dal cestino della galleria, finché ci restano. "
                f"Da qui posso solo togliere dal computer {copies}: lo faccio?")
    if entry["kind"] == "receive":
        return f"L'ultima modifica è stata copiare {_photos(count)} dal telefono nella cartella «{entry.get('folder', '')}». Tolgo {copies}? Sul telefono le foto restano."
    if entry["kind"] == "albums":
        return f"L'ultima modifica è stata copiare {_photos(count)} negli album dei viaggi. Tolgo {copies}? Gli originali non vengono toccati."
    return f"L'ultima modifica è stata copiare {_photos(count)} nella cartella «{entry.get('folder', '')}». Tolgo {copies}? Gli originali non vengono toccati."


def twins_in_words(groups: int, extra: int, phone: bool) -> str:
    """What was found of copies of the same picture, before the question: how many pictures have copies, and which are kept."""
    if groups == 1:
        copies = "una copia" if extra == 1 else f"{extra} copie"
        return f"Ho trovato 1 foto con {copies}. {'Ne tengo una' if phone else 'Tengo la versione più grande'}, questa:"
    kept = "ne tengo una" if phone else "tengo la versione più grande"
    return f"Ho trovato {groups} foto con delle copie, {extra} copie in più in tutto. Di ognuna {kept}, queste:"


def no_twins_in_words(indexed: int, phone: bool, period: str) -> str:
    """When no picture has a copy."""
    among = f"tra le {indexed} foto{' del telefono' if phone else ''}{f' {period}' if period else ''} che conosco"
    return f"Non ho trovato foto doppie {among}."


def albums_in_words(trips: list[dict]) -> str:
    """What was found of trips, before the question: the trips by name, and what a yes does."""
    named = [f"«{trip['name']}» ({_photos(len(trip['photos']))})" for trip in trips[:5]]
    listed = ", ".join(named) + (f" e altri {len(trips) - 5}" if len(trips) > 5 else "")
    found = "1 viaggio" if len(trips) == 1 else f"{len(trips)} viaggi, dal più recente"
    return (f"Ho trovato {found}: {listed}. Copio le foto di ogni viaggio in una cartella con il suo nome, in Raccolte? "
            "Gli originali restano dove sono, e puoi lasciare fuori un viaggio qui sotto.")


NO_TRIPS = ("Non ho trovato viaggi: servono foto in cui sia scritto dove sono state scattate, ad almeno 50 km da casa. "
            "Per casa intendo il posto dove ci sono le foto di più giorni diversi.")
ALBUMS_ONLY_HERE = "Gli album dei viaggi per ora li faccio con le foto del computer: quelle del telefono restano dove sono."


def _left_out(result: dict) -> str:
    """The pictures a change could not reach, said plainly."""
    text = ""
    if gone := result.get("missing"):
        text += f" {_photos(gone).capitalize()} non c'{'era' if gone == 1 else 'erano'} più."
    if stuck := result.get("failed"):
        text += f" {_photos(stuck).capitalize()} non sono riuscito a toccarl{'a: forse è aperta' if stuck == 1 else 'e: forse sono aperte'} in un altro programma."
    return text


def done_in_words(result: dict) -> tuple[str, str]:
    """What a confirmed change did: the words for the user, and what the model should remember of it."""
    count = result["count"]
    if result["kind"] == "trash":
        text = f"Fatto: {_photos(count)} nel cestino. Per riaverl{'a' if count == 1 else 'e'} basta dirmi «annulla»." if count else "Non ho spostato niente."
        memory = f"The user confirmed: {count} photos were moved to the trash."
    elif result["kind"] == "move":
        back = f"Per rimetterl{'a' if count == 1 else 'e'} dov'er{'a' if count == 1 else 'ano'} basta dirmi «annulla»."
        text = f"Fatto: {_photos(count)} spostat{'a' if count == 1 else 'e'} nella cartella «{result['folder']}». {back}" if count else "Non ho spostato niente."
        memory = f'The user confirmed: {count} photos were moved into the folder "{result["folder"]}".'
    elif result["kind"] == "albums":
        folders = result["folders"]
        into = f"nell'album «{folders[0]}»" if len(folders) == 1 else f"in {len(folders)} album, in Raccolte"
        text = f"Fatto: {_photos(count)} copiat{'a' if count == 1 else 'e'} {into}." if count else "Non ho copiato niente."
        memory = f"The user confirmed: {count} photos were copied into {len(folders)} trip albums: " + ", ".join(f'"{folder}"' for folder in folders) + "."
    else:
        text = f"Fatto: {_photos(count)} copiat{'a' if count == 1 else 'e'} nella cartella «{result['folder']}»." if count else "Non ho copiato niente."
        memory = f'The user confirmed: {count} photos were copied into the folder "{result["folder"]}".'
    return text + _left_out(result), memory


def undone_in_words(result: dict) -> tuple[str, str]:
    """What taking back a change did, for the user and for the model."""
    count = result["count"]
    if result["undid"] == "trash":
        if count:
            text = f"Annullato: {_photos(count)} di nuovo al {'suo' if count == 1 else 'loro'} posto."
        else:
            text = "Nel cestino quelle foto non ci sono più: non ho potuto rimetterle a posto."
        memory = f"The change was undone: {count} photos were restored from the trash."
    elif result["undid"] == "move":
        if count:
            text = f"Annullato: {_photos(count)} di nuovo dov'er{'a' if count == 1 else 'ano'}, fuori dalla cartella «{result['folder']}»."
        else:
            text = f"Nella cartella «{result['folder']}» quelle foto non ci sono più: non ho potuto rimetterle a posto."
        memory = f'The change was undone: {count} photos were moved back out of the folder "{result["folder"]}".'
    elif result["undid"] == "albums":
        text = f"Annullato: ho tolto {'la copia' if count == 1 else f'le {count} copie'} dagli album dei viaggi. Gli originali sono al loro posto."
        memory = f"The change was undone: {count} copies were removed from the trip albums."
    else:
        if result["undid"] != "receive":
            still = "Gli originali sono al loro posto."
        elif result.get("cleared"):
            still = "Sul telefono le trovi nel cestino della galleria, finché ci restano."
        else:
            still = "Sul telefono le foto ci sono ancora."
        text = f"Annullato: ho tolto {'la copia' if count == 1 else f'le {count} copie'} dalla cartella «{result['folder']}». {still}"
        memory = f'The change was undone: {count} copies were removed from the folder "{result["folder"]}".'
    if stuck := result.get("failed"):
        text += f" {_photos(stuck).capitalize()} non sono riuscito a spostarl{'a' if stuck == 1 else 'e'}: chiedimelo di nuovo tra poco."
    return text, memory


def no_trash_in_words(count: int) -> str:
    """Why a request to take pictures off a phone becomes a copy: before Android 11 there is no trash an app can use."""
    them = "la" if count == 1 else "le"
    return f"Questo telefono non ha un cestino che io possa usare (serve Android 11 o più recente), quindi non posso toglier{them}: posso solo copiar{them}."


def asked_in_words(count: int, folder: str, clear: bool = False) -> tuple[str, str]:
    """What is said when a phone has been asked for pictures and they have not arrived yet."""
    if clear:
        return (
            f"Ho chiesto al telefono {_photos(count)}. Quando sono al sicuro sul computer, il telefono ti chiede di spostarle nel suo cestino. Tieni Regista aperto sul telefono.",
            f'The user confirmed: the phone was asked for {count} photos, to be copied into the folder "{folder}" and then moved to the trash of the phone. Nothing has left the phone yet.',
        )
    return (
        f"Ho chiesto al telefono {_photos(count)}. Arrivano quando Regista è aperto sul telefono.",
        f'The user confirmed: the phone was asked for {count} photos, to be copied into the folder "{folder}". They arrive when the phone app is open.',
    )


def received_in_words(arrived: int, missing: int, folder: str) -> tuple[str, str]:
    """What is said when a phone has sent what it was asked for."""
    if arrived:
        text = f"Fatto: {_photos(arrived)} arrivat{'a' if arrived == 1 else 'e'} dal telefono, nella cartella «{folder}»."
    else:
        text = "Dal telefono non è arrivata nessuna foto."
    if missing:
        text += f" {_photos(missing).capitalize()} il telefono non è riuscito a mandarl{'a' if missing == 1 else 'e'}."
    return text, f'{arrived} photos arrived from the phone into the folder "{folder}".'


def sent_in_words(count: int, folder: str) -> tuple[str, str]:
    """What is said when pictures of the computer have been prepared for the phone, and it has not taken them yet."""
    return (
        f"Ho preparato {_photos(count)} per il telefono. Le prende quando Regista è aperto sul telefono.",
        f'The user confirmed: {count} photos are to go to the phone, into the album "{folder}". They arrive when the phone app is open.',
    )


def delivered_in_words(received: int, missing: int, folder: str) -> tuple[str, str]:
    """What is said when the phone has taken the pictures the computer prepared for it."""
    if received:
        text = f"Fatto: {_photos(received)} sul telefono, nell'album «{folder}»."
    else:
        text = "Sul telefono non è arrivata nessuna foto."
    if missing:
        text += f" {_photos(missing).capitalize()} non {'è arrivata' if missing == 1 else 'sono arrivate'}: forse sul computer non c'{'era' if missing == 1 else 'erano'} più."
    return text, f'{received} photos arrived on the phone, in the album "{folder}".'


def confirming_in_words(arrived: int, folder: str) -> str:
    """What is said while the phone asks its user whether the pictures, now copied, may go to its trash."""
    safe = "La foto è al sicuro" if arrived == 1 else f"Le {arrived} foto sono al sicuro"
    return f"{safe} sul computer, nella cartella «{folder}». Ora rispondi sul telefono alla domanda di Android, che le sposta nel suo cestino."


def cleared_in_words(arrived: int, trashed: int, missing: int, why: str, folder: str) -> tuple[str, str]:
    """What is said when a request to take pictures off a phone has ended, however it ended."""
    kept = f"La copia è sul computer, nella cartella «{folder}»."
    if not arrived:
        text = "Dal telefono non è arrivata nessuna foto, quindi non ne ho tolta nessuna."
    elif trashed:
        text = (f"Fatto: {_photos(trashed)} tolt{'a' if trashed == 1 else 'e'} dal telefono. "
                f"{'Resta' if trashed == 1 else 'Restano'} 30 giorni nel suo cestino, e una copia è sul computer nella cartella «{folder}».")
        if arrived > trashed:
            text += f" {_photos(arrived - trashed).capitalize()} sul telefono {'è rimasta' if arrived - trashed == 1 else 'sono rimaste'} dov'{'era' if arrived - trashed == 1 else 'erano'}."
    elif why == "old":
        text = f"Questo telefono non ha un cestino che io possa usare (serve Android 11 o più recente): le foto sono rimaste dov'erano. {kept}"
    else:
        text = f"Sul telefono hai detto di no: le foto sono rimaste dov'erano. {kept}"
    if missing:
        text += f" {_photos(missing).capitalize()} il telefono non è riuscito a mandarl{'a' if missing == 1 else 'e'}: non l{'a' if missing == 1 else 'e'} ho toccat{'a' if missing == 1 else 'e'}."
    return text, f'{arrived} photos were copied from the phone into the folder "{folder}"; {trashed} of them were then moved to the trash of the phone.'


def _searched(caption: str, phone: bool, when: tuple | None, there: str = "", both: bool = False) -> str:
    """A search as the model will remember it: in English, with what was looked for, on which device, of which place and days."""
    what = f' for "{caption}"' if caption else ""
    taken = (f" in {there}" if there else "") + (f" from {when[0]} to {when[1]}" if when else "")
    device = " on the computer and the phone" if both else " on the phone" if phone else ""
    return f'Searched the photos{device}{what}{" taken" + taken if taken else ""}'


def _also_on_the_phone(photos: list[dict]) -> str:
    """For a search of the computer and the phone together: how many of the pictures found are on the phone."""
    count = sum(1 for photo in photos if on_phone(photo["id"]))
    if not count:
        return ""
    return " Una è sul telefono." if count == 1 else f" {count} sono sul telefono."


def _at(spot: dict) -> str:
    """A place after "scattate": "a Parigi", "in Giappone", "negli Stati Uniti", "nelle Marche"."""
    if spot["kind"] == "city":
        return f"a {spot['name']}"
    if spot["kind"] == "region":
        return REGIONS[spot["code"]][2]
    return IN_COUNTRY.get(spot["code"], f"in {spot['name']}")


class Both:
    """The pictures of this computer and those of the phones, for a request that names neither: searched as one
    library, each picture still where it is. The ones of a phone say so ("place"), and on_phone tells them apart."""

    def __init__(self, photos, phones):
        self.parts = (photos, phones)
        self.state = photos.state

    @property
    def photos(self) -> list[dict]:
        return [*self.parts[0].photos, *self.parts[1].photos]

    def thumbnail(self, identifier: str) -> bytes | None:
        return (self.parts[1] if on_phone(identifier) else self.parts[0]).thumbnail(identifier)

    def to_look_at(self, description: str, period: tuple | None = None, spot: dict | None = None) -> list[dict]:
        here, there = (part.to_look_at(description, period, spot) for part in self.parts)
        there = [{**candidate, "place": "phone"} for candidate in there]
        # each list keeps its own order, the likeliest first; of the two, the one whose next picture is closer to the words goes first
        return list(heapq.merge(here, there, key=lambda candidate: -candidate["score"]))[:LOOK_MOST]

    def search(self, description: str, limit: int = 60, period: tuple | None = None, spot: dict | None = None) -> dict:
        here, there = (part.search(description, limit, period, spot) for part in self.parts)
        marked = [{**photo, "place": "phone"} for photo in [*there["sure"], *there["maybe"]]]
        # the closest of both, as one search would choose them; shown the newest first
        found = sorted([*here["sure"], *here["maybe"], *marked], key=lambda photo: (-photo["score"], newest(photo)))[:limit]
        return {
            "sure": sorted((photo for photo in found if photo["score"] >= SURE), key=newest),
            "maybe": sorted((photo for photo in found if photo["score"] < SURE), key=newest),
            "matching": here["matching"] + there["matching"],
            "indexed": here["indexed"] + there["indexed"],
        }


def look(library, caption: str, limit: int, when: tuple | None, spot: dict | None, device: str | None = None) -> tuple[dict, bool]:
    """Searches the pictures for what a request names. Says also whether they were found by where they were taken.

    When the request names a place, the pictures taken there are the answer. But many pictures
    have no position written in them: if none turns out to be from there, the search is for
    the pictures that look like the place, as it was before places were known. With a `device`,
    only the pictures of that phone are looked at.
    """
    search = functools.partial(library.search, device=device) if device else library.search
    if spot:
        result = search(spot["rest"], limit, when, spot)
        if result["sure"] or result["maybe"]:
            return result, True
    return search(caption, limit, when), False


def propose(decision: dict, photos, actions, selection: list[str], phones=None, phone: bool = False, when: tuple | None = None, spot: dict | None = None,
            to_phone: bool = False, looked: dict | None = None) -> dict:
    """What a request to change the pictures becomes: words, and a proposal for the user to confirm.

    Nothing is touched here. `selection` is the pictures the user is looking at, by their
    short names: they are what "these" means. `phone` says that the request names the
    phone as the place of the pictures. `looked` is what a looking one by one found
    (_looking), when the pictures were looked at: then those are the ones proposed.
    """
    period = period_in_words(when) if when else ""

    def only(text: str, memory: str, searched: str = "") -> dict:
        return {"text": text, "memory": memory, "proposal": None, "searched": searched, "period": period if searched or when else "", "spot": ""}

    if not actions.writable():
        return only(READ_ONLY, "The photo folder is read-only: nothing can be changed.")

    if decision["action"] == "undo":
        last = actions.last()
        if last is None:
            return only(NOTHING_TO_UNDO, "There was nothing to undo.")
        proposal = {
            "action": "undo",
            "of": last["id"],
            "undoes": last["kind"],
            "folder": last.get("folder", ""),
            "count": len(last["files"]),
            "when": last["when"],
        }
        memory = "Proposed to undo the last change. Nothing was done: the user must confirm."
        return {"text": undo_proposed_in_words(last), "memory": memory, "proposal": proposal, "searched": "", "period": "", "spot": ""}

    kind = {"trash_photos": "trash", "move_photos": "move"}.get(decision["action"], "copy")
    caption, folder = decision["caption"], ""
    if to_phone:
        # pictures of the computer, to go to the phone
        if phones is None or not phones.devices:
            return only(NO_PHONE, "No phone is connected.")
        if not caption and not when and bool(selection) and all(on_phone(identifier) for identifier in selection):
            return only(ALREADY_THERE, "The photos the user meant are already on the phone.")
        kind = "send"
    # the pictures are on the phone if the request says so, or if "these" are pictures of the phone
    away = not to_phone and (phone or (not caption and not when and bool(selection) and all(on_phone(identifier) for identifier in selection)))
    if away:
        if phones is None or not phones.devices:
            return only(NO_PHONE, "No phone is connected.")
        if not phones.photos:
            return only(PHONE_EMPTY, "The phone has not sent its photos yet.")
        # thrown away or moved off a phone means: a copy here first, and then the phone's own trash
        kind = "clear" if kind in ("trash", "move") else "fetch"
    if kind == "clear":
        # moved off it, into the folder the user named; thrown away, into the folder of the ones taken off phones
        folder = REMOVED
        if decision["action"] == "move_photos" and decision["folder"]:
            try:
                folder = collection_name(decision["folder"])
            except Refused:
                pass
    elif kind == "send":
        # an album on the phone: when the request names none, one with a name that says where its pictures came from
        try:
            folder = collection_name(decision["folder"] or FROM_COMPUTER)
        except Refused:
            folder = FROM_COMPUTER
    elif kind != "trash":
        try:
            folder = collection_name(decision["folder"])
        except Refused:
            pass  # no usable name: the proposal is made all the same, and the page asks for the name
    left = 0
    if looked is not None:
        # the pictures were looked at one by one: the ones the eyes confirmed, and no other
        there, caption = looked["there"], looked["looking_for"]
        chosen, every = looked["found"][:MOST], len(looked["found"])
        if not chosen:
            return only(NONE_LIKE_THAT, f"{_searched(caption, away, when)}: looked at {looked['looked']} one by one, none shows it, so nothing was proposed.", caption)
    elif caption or when:
        # the message says which pictures, by what they show or by when they were taken:
        # only the ones the search is sure about are proposed
        result, there = look(phones if away else photos, caption, MOST, when, spot)
        if there:
            caption = spot["rest"]
        chosen, every = result["sure"], result["matching"]
        if not chosen:
            return only(NONE_LIKE_THAT, f"{_searched(caption, away, when)}: none found, so nothing was proposed.", caption)
    else:
        there = False
        if away:
            known = {photo["id"]: photo["name"] for photo in phones.photos}
        else:
            known = {photo["id"]: photo["path"].rsplit("/", 1)[-1] for photo in photos.photos}
        chosen = [{"id": identifier, "name": known[identifier]} for identifier in dict.fromkeys(selection) if identifier in known][:MOST]
        every = len(chosen)
        if not chosen:
            return only(WHICH_ONES, "No photos were chosen, so nothing was proposed.")
        # pictures of the computer and of a phone on screen together: the ones of the phone are not touched from here
        left = 0 if away or kind == "send" else sum(1 for identifier in dict.fromkeys(selection) if on_phone(identifier))

    # a phone with no trash an app can use can only be copied from: said before the question, and not hidden in it
    old = kind == "clear" and not phones.can_trash([photo["id"] for photo in chosen])
    if old:
        kind, folder = "fetch", FROM_THE_PHONE if folder == REMOVED else folder
    into = f'into the folder "{folder}"' if folder else "into a folder that has no name yet"
    what = {
        "trash": "move them to the trash",
        "copy": f"copy them {into}",
        "move": f"move them {into}",
        "fetch": f"copy them from the phone to the computer, {into}",
        "clear": f"copy them from the phone to the computer, {into}, and then move them to the trash of the phone",
        "send": f'send them to the phone, into the album "{folder}"',
    }[kind]
    # with the caption, so that the next request can build on this search too
    searched = f"{_searched(caption, away, when, spot['name'] if there else '')}: {every} found. " if caption or when or there else ""
    if old:
        searched += "The phone has no trash an app can use (its Android is older than 11), so the photos cannot be taken off it. "
    aside = f"{_photos(left).capitalize()} del telefono non {'la' if left == 1 else 'le'} tocco da qui: per {'quella' if left == 1 else 'quelle'} dimmelo con «dal telefono». " if left else ""
    return {
        "text": aside + (f"{no_trash_in_words(len(chosen))} " if old else "") + proposed_in_words(kind, len(chosen), folder, every),
        # nothing has changed yet, and the model must not think it has
        "memory": f"{searched}Proposed to {what} ({len(chosen)} photos). Nothing was done: the user must confirm.",
        "proposal": {"action": kind, "folder": folder, "photos": [{"id": photo["id"], "name": photo["name"]} for photo in chosen]},
        "searched": caption,
        "period": period if caption or when else "",
        "spot": _at(spot) if there else "",
    }


async def _twins(asked: str, photos, actions, phones):
    """Copies of the same picture: the ones kept are shown, and the others proposed for the trash.

    On the phone ("le foto doppie del telefono") they go first to the computer and then to the phone's
    own trash, as any picture taken off it. Each copy kept is the one with the most pixels on the
    computer; on the phone, where only small copies are known here, the one taken first.
    """
    phone = phones is not None and bool(ON_PHONE.search(asked))
    when = read_period(asked)
    period = period_in_words(when) if when else ""
    place = "phone" if phone else "computer"
    yield {"type": "step", "tool": "find_twins", "arguments": {"place": place, "period": period}}
    if phone and not phones.devices:
        yield {"type": "text", "text": NO_PHONE}
        yield {"type": "done", "memory": "No phone is connected."}
        return
    library = phones if phone else photos
    if not library.photos:
        yield {"type": "text", "text": PHONE_EMPTY if phone else NO_PHOTOS}
        yield {"type": "done", "memory": "There were no photos to look at."}
        return
    groups = await asyncio.to_thread(library.twins, when)
    on = " on the phone" if phone else ""
    if not groups:
        # how many pictures were looked at: those of the period, when one was named
        looked_at = sum(1 for photo in library.photos if not when or when[0].isoformat() <= photo.get("day", "") <= when[1].isoformat())
        yield {"type": "text", "text": no_twins_in_words(looked_at, phone, period)}
        yield {"type": "done", "memory": f"Looked for copies of the same photo{on}: none found."}
        return
    # the newest first, as a search shows them
    groups.sort(key=lambda group: group[0]["day"], reverse=True)
    kept = [group[0] for group in groups]
    extra = [photo for group in groups for photo in group[1:]]
    yield {"type": "text", "text": twins_in_words(len(groups), len(extra), phone)}
    yield {"type": "photos", "description": "", "place": place, "partial": False, "indexed": len(library.photos), "matching": len(kept),
           "sure": [{"id": photo["id"], "name": photo["name"], "score": 1.0} for photo in kept], "maybe": []}
    found = f"Found {len(groups)} photos{on} with copies, {len(extra)} copies in all; the first of each was kept and shown."
    if actions is None or not actions.writable():
        yield {"type": "text", "text": READ_ONLY}
        yield {"type": "done", "memory": f"{found} The photo folder is read-only: nothing was proposed."}
        return
    chosen = extra[:MOST]
    kind, folder = ("clear", REMOVED) if phone else ("trash", "")
    old = phone and not phones.can_trash([photo["id"] for photo in chosen])
    if old:
        kind, folder = "fetch", FROM_THE_PHONE
    question = proposed_in_words(kind, len(chosen), folder, len(extra))
    yield {"type": "text", "text": f"{no_trash_in_words(len(chosen)) + ' ' if old else ''}{question}"}
    yield {"type": "proposal", "action": kind, "folder": folder, "photos": [{"id": photo["id"], "name": photo["name"]} for photo in chosen]}
    what = {"trash": "move them to the trash", "clear": "copy them to the computer and then move them to the trash of the phone",
            "fetch": "copy them from the phone to the computer (it has no trash an app can use)"}[kind]
    yield {"type": "done", "memory": f"{found} Proposed to {what} ({len(chosen)} copies). Nothing was done: the user must confirm."}


async def _albums(asked: str, photos, actions, phones):
    """An album for each trip: the trips are worked out from where and when the pictures were taken (trips.py), and copying them is proposed."""
    yield {"type": "step", "tool": "make_albums", "arguments": {}}
    if phones is not None and ON_PHONE.search(asked):
        yield {"type": "text", "text": ALBUMS_ONLY_HERE}
        yield {"type": "done", "memory": "Trip albums are made only of the photos of the computer."}
        return
    if not photos.photos:
        yield {"type": "text", "text": NO_PHOTOS}
        yield {"type": "done", "memory": "There were no photos to look at."}
        return
    trips = await asyncio.to_thread(photos.trips)
    if not trips:
        yield {"type": "text", "text": NO_TRIPS}
        yield {"type": "done", "memory": "Looked for trips among the photos: none found."}
        return
    names = ", ".join(f'"{trip["name"]}" ({len(trip["photos"])} photos)' for trip in trips)
    if actions is None or not actions.writable():
        yield {"type": "text", "text": f"Ho trovato {len(trips)} viaggi. {READ_ONLY}"}
        yield {"type": "done", "memory": f"Found {len(trips)} trips: {names}. The photo folder is read-only: nothing was proposed."}
        return
    yield {"type": "text", "text": albums_in_words(trips)}
    yield {
        "type": "proposal",
        "action": "albums",
        "folder": "",
        "photos": [{"id": photo["id"], "name": photo["name"]} for trip in trips for photo in trip["photos"]],
        "albums": [{"folder": trip["name"], "ids": [photo["id"] for photo in trip["photos"]]} for trip in trips],
    }
    yield {"type": "done", "memory": f"Found {len(trips)} trips: {names}. Proposed to copy the photos of each into a folder with its name. Nothing was done: the user must confirm."}


# What the eyes said of a picture for a question, so that a search made again does not ask again.
_seen: dict[tuple, bool] = {}
# how long a request typed on a phone may look at pictures: the phone waits a minute for the answer
PHONE_LOOKING = 40
def _for_the_eyes(library, identifier: str) -> bytes | None:
    """The small copy of a picture, as the model that looks is shown it (photos.EYES)."""
    picture = library.thumbnail(identifier)
    return for_the_eyes(picture) if picture else None


# When the model that looks was last made sure to sit in the graphics card as much as it can (_ready_to_look).
_checked = 0.0
CHECK_EVERY = 600


async def _ready_to_look(model: str | None, tests: dict) -> None:
    """Before a request: since Regista started, Ollama may have loaded the model again (after half an hour of rest)
    with less of it in the graphics card than it can have, as when other programs held some of the card; then a
    picture takes 1.5 to 2.5 seconds instead of 1. So it is loaded again (llm.ready), but at most every ten
    minutes, as a reload that helps nothing costs seconds; and only for a model whose share the test measured."""
    global _checked
    share = tests.get(model, {}).get("gpu_share") if model else None
    if share is None or time.monotonic() - _checked < CHECK_EVERY:
        return
    _checked = time.monotonic()
    try:
        await llm.ready(model, share)
    except Exception:
        logger.exception("the model could not be loaded again: the request goes on with it as it is")


# How many pictures the eyes are asked about at once (llm.sees_many). Four at a time took 0.69 seconds a picture
# against 1.04, and found as many of the right ones; but asked about things none of the 200 samples shows, they
# said yes 6 times in 200 against 3. Being right comes first: one at a time.
GROUP = 1


async def _looking(library, phone: bool, caption: str, when, spot: dict | None, period: str, eyes: str, english: bool, outcome: dict,
                   device: str | None = None, seconds: float | None = None):
    """Pictures looked at one by one by a model that sees, as events: "step", "photos" (none yet, and how many
    there are to look at), then "photo" for each one it confirms and "looked" after each. What was found
    is left in `outcome`.

    The period and the place are kept exactly, as the pictures' own notes say them; what the pictures
    show is first ranked by numbers (photos.to_look_at), likeliest first, and then looked at, GROUP at a
    time, each judged by itself. The
    looking stops after LOOK_STOP wrong in a row, at LOOK_MOST or after `seconds`, and never asks twice
    about the same picture. The model is asked in English, which it reads best; in Italian when the
    caption is not a translation but the user's own words (`english` False). With a `device`, only the
    pictures of that phone.
    """
    place = "phone" if phone else "both" if isinstance(library, Both) else "computer"
    to_look_at = functools.partial(library.to_look_at, device=device) if device else library.to_look_at
    candidates = await asyncio.to_thread(to_look_at, spot["rest"], when, spot) if spot and spot["rest"] else []
    there = bool(candidates)
    looking_for = spot["rest"] if there else caption
    if not there:
        candidates = await asyncio.to_thread(to_look_at, caption, when, None)
    yield {"type": "step", "tool": "find_photos", "arguments": {"description": looking_for, "place": place, "period": period, "spot": _at(spot) if there else ""}}
    partial = False if phone else library.state["running"]
    yield {"type": "photos", "description": looking_for, "place": place, "sure": [], "maybe": [], "matching": 0,
           "indexed": len(library.photos), "partial": partial, "checking": len(candidates), "looked": 0}
    if spot and not there:
        yield {"type": "text", "text": f"Nessuna foto risulta scattata {_at(spot)}: cerco quelle che ci somigliano."}
    # what the answers are remembered under: the picture, and the question about it
    question = llm.question(looking_for, english)
    found, looked, wrong, broken, late = [], 0, 0, "", False
    started = time.perf_counter()
    for first in range(0, len(candidates), GROUP):
        if wrong >= LOOK_STOP:
            break
        if seconds is not None and time.perf_counter() - started > seconds:
            late = True
            break
        group = candidates[first:first + GROUP]
        unknown = [candidate for candidate in group if (place, candidate["id"], question) not in _seen]
        if unknown:
            pictures = [await asyncio.to_thread(_for_the_eyes, library, candidate["id"]) for candidate in unknown]
            shown = [(candidate, picture) for candidate, picture in zip(unknown, pictures) if picture]
            try:
                said = await llm.sees_many(eyes, [picture for _, picture in shown], looking_for, english) if shown else []
            except Exception as exc:  # Ollama stopped, or the model failed: what was confirmed stays
                broken = f"{type(exc).__name__}: {exc}"
                break
            while len(_seen) > 20_000 - GROUP:
                _seen.pop(next(iter(_seen)))
            # a picture whose small copy cannot be made shows nothing
            _seen.update({(place, candidate["id"], question): False for candidate in unknown})
            _seen.update({(place, candidate["id"], question): yes for (candidate, _), yes in zip(shown, said)})
        for candidate in group:
            looked += 1
            if _seen[(place, candidate["id"], question)]:
                photo = {"id": candidate["id"], "name": candidate["name"], "day": candidate["day"], "score": candidate["score"]}
                if on_phone(candidate["id"]):
                    photo["place"] = "phone"
                found.append(photo)
                wrong = 0
                yield {"type": "photo", "photo": photo}
            else:
                wrong += 1
            yield {"type": "looked", "looked": looked, "of": len(candidates)}
            if wrong >= LOOK_STOP:
                break
    # the looking is over: the page stops saying it goes on
    yield {"type": "looked", "looked": looked, "of": looked}
    outcome.update({
        "found": found, "looked": looked, "candidates": len(candidates), "there": there, "looking_for": looking_for, "place": place,
        "broken": broken, "partial": partial,
        # stopped with pictures still to look at, while they were still being confirmed
        "cut": late or (looked == len(candidates) == LOOK_MOST and wrong < LOOK_STOP),
    })


def looked_in_words(outcome: dict, phone: bool, spot: dict | None, period: str, known: bool = True) -> str:
    """What a looking one by one found, said by the app: the numbers are counted here, never written by a model."""
    found, looked = len(outcome["found"]), outcome["looked"]
    taken = f"scattat{'a' if found == 1 else 'e'} {_at(spot)}" if outcome["there"] else ""
    where = " ".join(filter(None, ["sul telefono" if phone else "", taken, period]))
    where = f" {where}" if where else ""
    if outcome["broken"] and not looked:
        words = "Non ho potuto guardare le foto: il modello che le guarda non risponde."
    elif found:
        words = f"Ho trovato {_photos(found)}{where}: le ho guardate una per una, dalla più recente."
        if outcome.get("place") == "both":
            words += _also_on_the_phone(outcome["found"])
    elif outcome["candidates"]:
        words = f"Ne ho guardate {looked}{where} una per una: nessuna mostra quello che hai chiesto."
    else:
        words = NO_PHOTOS if not known else f"Non ho foto{where} in cui cercare."
    if outcome["broken"] and looked:
        words += " Mi sono fermato prima della fine: il modello che guarda le foto non risponde."
    elif outcome["cut"]:
        words += " Mi sono fermato prima di guardarle tutte: potrebbero essercene altre."
    if outcome["partial"]:
        words += " Sto ancora leggendo le foto, quindi il risultato è parziale."
    return words


async def _one_by_one(library, phone: bool, caption: str, when, spot: dict | None, period: str, eyes: str, english: bool = True):
    """A search whose pictures are looked at one by one (_looking): the ones confirmed are sent as they are, and
    the page keeps them the newest first; then the words."""
    outcome: dict = {}
    async for event in _looking(library, phone, caption, when, spot, period, eyes, english, outcome):
        yield event
    yield {"type": "text", "text": looked_in_words(outcome, phone, spot, period, bool(library.photos) or phone)}
    there = spot["name"] if outcome["there"] else ""
    both = outcome["place"] == "both"
    yield {"type": "done", "memory": f'{_searched(outcome["looking_for"], phone, when, there, both)}: looked at {outcome["looked"]} one by one, {len(outcome["found"])} show it.'}


async def on_the_phone(text: str, device: str, phones, places, models: list[dict], machine, tests: dict) -> dict | None:
    """A request typed on a phone's own screen, understood here: the pictures of that phone it asks for, and the words.

    The phone reads a request by itself too (understand.ts), with no model. Here the director
    understands what that cannot, and this computer's model, which reads English best, looks
    for what the pictures show: with a model that sees, the likeliest are looked at one by one,
    for at most PHONE_LOOKING seconds. The pictures are named as the phone names them. None when
    this computer has nothing to add: then the phone's own answer stands.
    """
    director, eyes = catalog.director_and_eyes(models, machine, tests)
    if director is None or not any(photo["device"] == device for photo in phones.photos):
        return None
    started = time.perf_counter()
    await _ready_to_look(eyes or director, tests)
    decision = await decide(director, [{"role": "user", "content": text}])
    if decision["action"] == "answer" and FIND.search(text) and not HOW.search(text):
        decision = {"action": "find_photos", "caption": own_words(text), "folder": "", "own": True}
    caption = re.sub(r"\s+", " ", PLACE_WORDS.sub(" ", decision["caption"])).strip()
    when = read_period(text)
    if when:
        caption = without_time(caption)
    if not caption and not when:
        return None
    period = period_in_words(when) if when else ""
    spot, rest = places.find(caption, text) if places is not None and caption else (None, caption)
    if spot:
        spot = {**spot, "rest": rest}
    media = {photo["id"]: photo["media"] for photo in phones.photos if photo["device"] == device}
    if eyes and (spot["rest"] if spot else caption):
        outcome: dict = {}
        async for _ in _looking(phones, True, caption, when, spot, period, eyes, not decision.get("own"), outcome, device, PHONE_LOOKING):
            pass
        words = looked_in_words(outcome, False, spot, period)
        if spot and not outcome["there"]:
            words = f"Nessuna foto risulta scattata {_at(spot)}: cerco quelle che ci somigliano. {words}"
        sure, maybe = sorted(outcome["found"], key=newest), []
    else:
        result, there = await asyncio.to_thread(look, phones, caption, PHONE_SHOWN, when, spot, device)
        taken = f"scattat{'a' if result['matching'] == 1 and len(result['sure']) <= 1 else 'e'} {_at(spot)}" if there else ""
        words = found_in_words(result, False, " ".join(filter(None, [taken, period])), bool(spot["rest"] if there else caption))
        if spot and not there:
            words = f"Nessuna foto risulta scattata {_at(spot)}: cerco quelle che ci somigliano. {words}"
        sure, maybe = result["sure"], result["maybe"]
    return {
        "words": words,
        "sure": [media[photo["id"]] for photo in sure if photo["id"] in media],
        "maybe": [media[photo["id"]] for photo in maybe if photo["id"] in media],
        "model": director,
        "seconds": round(time.perf_counter() - started, 1),
    }


def _conversation(history: list[dict], system: str) -> list[dict]:
    """The last messages of the conversation, with the instructions in front."""
    kept = [
        {"role": message["role"], "content": str(message.get("content", ""))}
        for message in history[-HISTORY:]
        if message.get("role") in ("user", "assistant")
    ]
    return [{"role": "system", "content": system}, *kept]


async def decide(model: str, history: list[dict]) -> dict:
    """What to do with the last message: {"action": one of ACTIONS, "caption", "folder"}.

    Anything the model writes that is not a valid form counts as "answer": talking is
    the one thing that can never do harm.
    """
    text = ""
    async for kind, value in llm.stream(model, _conversation(history, DECIDE), max_tokens=DECISION_TOKENS, schema=DECISION):
        if kind == "text":
            text += value
    try:
        form = json.loads(text)
        action = form["action"] if form.get("action") in ACTIONS else "answer"
        return {"action": action, "caption": str(form.get("caption") or "").strip(), "folder": str(form.get("folder") or "").strip()}
    except (ValueError, AttributeError, TypeError):
        return {"action": "answer", "caption": "", "folder": ""}


async def reply(history: list[dict], wanted: str, models: list[dict], machine, tests: dict, photos, actions=None,
                selection: list[str] | None = None, phones=None, places=None):
    """One reply as a stream of events, so that the page can show it while it happens.

    "start" says which models are at work, "step" and "photos" carry a search and what it
    found, "proposal" a change that waits for the user's yes, "text" the words, and "done"
    closes with what to remember of this turn.
    """
    started = time.perf_counter()
    director, eyes = catalog.director_and_eyes(models, machine, tests)
    writer = catalog.writer(models, machine, tests, wanted, director)
    await _ready_to_look(eyes or director, tests)
    if writer is None:
        yield {"type": "text", "text": NO_MODEL}
        yield {"type": "done", "model": "", "seconds": 0, "memory": NO_MODEL}
        return
    loaded = {model["name"] for model in models if model["loaded"]}
    asked = next((str(message.get("content", "")) for message in reversed(history) if message.get("role") == "user"), "")
    # copies of the same picture, and albums of trips, are worked out by the app: no model is asked
    if TWINS.search(asked) or ALBUMS.search(asked):
        yield {"type": "start", "director": director, "writer": writer, "loading": False}
        app_made = _twins(asked, photos, actions, phones) if TWINS.search(asked) else _albums(asked, photos, actions, phones)
        async for event in app_made:
            yield {**event, "model": director or writer, "seconds": round(time.perf_counter() - started, 1)} if event["type"] == "done" else event
        return
    yield {"type": "start", "director": director, "writer": writer, "loading": (director or writer) not in loaded}

    # without a model that can direct, the app can still talk
    decision = await decide(director, history) if director else {"action": "answer", "caption": "", "folder": ""}
    if director and decision["action"] == "answer" and FIND.search(asked) and not HOW.search(asked):
        # the model gave no caption: what the pictures should show is said in the user's own words
        decision = {"action": "find_photos", "caption": own_words(asked), "folder": "", "own": True}
    # the place is not something a picture shows: out of the caption, whatever the model left in it
    decision["caption"] = re.sub(r"\s+", " ", PLACE_WORDS.sub(" ", decision["caption"])).strip()
    # The period a request names is read here, in its words, and not asked to the model (period.py).
    # And a picture does not show its date: what the model left of it in the caption comes out.
    when = read_period(asked)
    if when:
        decision["caption"] = without_time(decision["caption"])
    period = period_in_words(when) if when else ""
    action, caption = decision["action"], decision["caption"]
    # The place a request names, if the caption has one that the table of places knows (places.py):
    # then the pictures are looked for by where they were taken, and by what else the caption says.
    spot, rest = places.find(caption, asked) if places is not None and caption else (None, caption)
    if spot:
        spot = {**spot, "rest": rest}
    # on the phone when the request says so; and when it names no place, where the pictures on screen are
    looking_there = bool(selection) and all(on_phone(identifier) for identifier in selection)
    # "salvale sul computer" names where pictures go, not where they are: only a search is moved by it
    elsewhere = action in ("find_photos", "count_photos") and bool(ON_COMPUTER.search(asked))
    # "mandale sul telefono" names where pictures go: they are the computer's
    goes = phones is not None and bool(TO_PHONE.search(asked)) and not FROM_PHONE.search(asked)
    if goes and action == "find_photos" and SENDS.search(asked):
        action = decision["action"] = "copy_photos"
    # to the phone, moving is copying: the phone takes a copy, and the computer keeps its pictures
    to_phone = action in ("copy_photos", "move_photos") and goes
    phone = phones is not None and not to_phone and (bool(ON_PHONE.search(asked)) or (looking_there and not elsewhere))
    # a search that names neither the computer nor the phone looks at both, once a phone has said what pictures it has
    both = phones is not None and not phone and not elsewhere and action in ("find_photos", "count_photos") and bool(phones.photos)

    def done(model: str, memory: str, **more) -> dict:
        return {"type": "done", "model": model, "seconds": round(time.perf_counter() - started, 1), "memory": memory, **more}

    if phone and action in ("count_photos", "find_photos") and not phones.devices:
        yield {"type": "text", "text": NO_PHONE}
        yield done(director, "No phone is connected.")
        return

    if action == "count_photos":
        library = phones if phone else photos
        indexed = library.search("", 1, when)["matching"] if when else len(library.photos)
        yield {"type": "step", "tool": "count_photos", "arguments": {}}
        if both:
            there = phones.search("", 1, when)["matching"] if when else len(phones.photos)
            yield {"type": "text", "text": f"Conosco {_photos(indexed)} sul computer e {_photos(there)} sul telefono{f' {period}' if when else ''}."}
            yield done(director, f"Counted the photos{f' taken from {when[0]} to {when[1]}' if when else ''}: {indexed} on the computer, {there} on the phone.")
            return
        if phone:
            yield {"type": "text", "text": f"Conosco {_photos(indexed)} del telefono{f' {period}' if when else ''}." if indexed or when else PHONE_EMPTY}
        elif when:
            yield {"type": "text", "text": f"Conosco {_photos(indexed)} {period}."}
        else:
            yield {"type": "text", "text": counted_in_words(photos.state, indexed)}
        taken = f" taken from {when[0]} to {when[1]}" if when else ""
        yield done(director, f"Counted the photos{' on the phone' if phone else ''}{taken}: {indexed}.")
        return

    if action == "find_photos":
        if not caption and not when:
            yield {"type": "text", "text": UNCLEAR}
            yield done(director, "The search could not start: no description was given.")
            return
        place = "phone" if phone else "both" if both else "computer"
        library = phones if phone else Both(photos, phones) if both else photos
        if eyes and (spot["rest"] if spot else caption):
            # what the pictures show is checked by looking at them, one by one, as they are shown
            async for event in _one_by_one(library, phone, caption, when, spot, period, eyes, not decision.get("own")):
                yield {**event, "model": director, "seconds": round(time.perf_counter() - started, 1)} if event["type"] == "done" else event
            return
        # what a period or a place asks for is all of its pictures, not the first few
        every = not (spot["rest"] if spot else caption)
        result, there = await asyncio.to_thread(look, library, caption, EVERY if every else 60, when, spot)
        if there:
            caption = spot["rest"]
        yield {"type": "step", "tool": "find_photos", "arguments": {"description": caption, "place": place, "period": period, "spot": _at(spot) if there else ""}}
        result["partial"] = False if phone else photos.state["running"]
        yield {"type": "photos", "description": caption, "place": place, **result}
        # "1 foto scattata", "3 foto scattate"
        taken = f"scattat{'a' if result['matching'] == 1 and len(result['sure']) <= 1 else 'e'} {_at(spot)}" if there else ""
        words = found_in_words(result, phone, " ".join(filter(None, [taken, period])), bool(caption))
        if both and result["sure"]:
            words += _also_on_the_phone(result["sure"])
        if spot and not there:
            # the place was understood, and no picture says it was taken there
            words = f"Nessuna foto risulta scattata {_at(spot)}: cerco quelle che ci somigliano. {words}"
        yield {"type": "text", "text": words}
        # in English and with the caption, so that "only the black ones" can build on it
        yield done(director, f'{_searched(caption, phone, when, spot["name"] if there else "", both)}: {result["matching"]} found, {len(result["maybe"])} uncertain.')
        return

    if action in CHANGES and actions is not None:
        looked = None
        library = phones if phone and not to_phone else photos
        if (eyes and action != "undo" and (spot["rest"] if spot else caption) and actions.writable() and library is not None
                and library.photos and (library is photos or phones.devices)):
            # which pictures, by what they show: looked at one by one as for a search, and only the ones confirmed are
            # proposed. The page shows how far the looking is, and the pictures once, in the proposal.
            looked = {}
            async for event in _looking(library, library is phones, caption, when, spot, period, eyes, not decision.get("own"), looked):
                if event["type"] != "photo":
                    yield event
        plan = await asyncio.to_thread(propose, decision, photos, actions, selection or [], phones, phone, when, spot, to_phone, looked)
        if looked is None and (plan["searched"] or plan["period"] or plan["spot"]):
            found = {"description": plan["searched"], "place": "phone" if phone else "computer", "period": plan["period"], "spot": plan["spot"]}
            yield {"type": "step", "tool": "find_photos", "arguments": found}
        if looked and looked["broken"] and plan["proposal"]:
            plan["text"] += " Mi sono fermato prima della fine: il modello che guarda le foto non risponde, quindi potrebbero mancarne."
        yield {"type": "text", "text": plan["text"]}
        if plan["proposal"]:
            yield {"type": "proposal", **plan["proposal"]}
        yield done(director, plan["memory"])
        return

    text, stats = "", {}
    async for kind, value in llm.stream(writer, _conversation(history, TALK)):
        if kind == "text":
            text += value
            yield {"type": "text", "text": value}
        if kind == "stats":
            stats = value
    yield done(writer, text, tokens_per_second=stats.get("tokens_per_second", 0))
