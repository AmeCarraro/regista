"""The orchestrator: reads a request, decides what to do with it, and does it.

It works in two moves. First one model, the "director", decides: answer in words,
search the pictures, count them, throw some away, copy some, take a change back.
It must reply with a small form, not with free text, so the decision is always one the
app can carry out. Then the app acts, and says what happened from what happened: the
numbers in a reply are counted by the app and never written by a model.

A model never changes a picture. A request to throw away, copy or undo becomes a
proposal: the page shows it, and it is carried out only when the user says yes there
(main.py). So a wrong decision costs a click on "no", and nothing else.

The decision is a form, with examples, because a small model left free to call tools
calls them too often: asked for advice on taking pictures, it searched the pictures.
"""
import asyncio
import json
import re
import time

import catalog
import llm
from actions import Refused, collection_name
from period import in_words as period_in_words
from period import read as read_period
from period import without_time
from phone import on_phone

ACTIONS = ("answer", "find_photos", "count_photos", "trash_photos", "copy_photos", "undo")
# the decisions that would change the pictures: they are proposed, never carried out here
CHANGES = ("trash_photos", "copy_photos", "undo")

# A request is about the pictures of the phone when it names the phone as a place: "sul telefono",
# "dal mio cellulare". This is read here, in the words of the user, and not asked to the model:
# the model has enough to decide already. "Una foto con un telefono" is a picture of a phone, not this.
ON_PHONE = re.compile(
    r"\b(?:dal|sul|nel|del|al)\s+(?:mio\s+)?(?:telefono|telefonino|cellulare|smartphone)\b"
    r"|\b(?:on|from|in)\s+(?:my|the)\s+(?:phone|smartphone)\b",
    re.IGNORECASE,
)
ON_COMPUTER = re.compile(r"\b(?:dal|sul|nel|del|al)\s+(?:mio\s+)?(?:computer|pc)\b|\b(?:on|from|in)\s+(?:my|the)\s+(?:computer|pc)\b", re.IGNORECASE)
# what a model may leave in a caption about the place, and that the pictures do not show
PLACE_WORDS = re.compile(r"\b(?:on|from|in|of)\s+(?:my\s+|the\s+)?(?:phone|smartphone|cellphone|mobile|computer|pc)\b", re.IGNORECASE)

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
    'come faccio a fotografare la luna? -> {"action": "answer", "caption": "", "folder": ""}\n'
    'quale obiettivo mi consigli per i ritratti? -> {"action": "answer", "caption": "", "folder": ""}\n'
    'perfetto, grazie -> {"action": "answer", "caption": "", "folder": ""}\n'
    'quante immagini ci sono? -> {"action": "count_photos", "caption": "", "folder": ""}\n'
    'eliminale -> {"action": "trash_photos", "caption": "", "folder": ""}\n'
    'butta via le foto dei tramonti -> {"action": "trash_photos", "caption": "a sunset", "folder": ""}\n'
    'mettile in una cartella chiamata Vacanze -> {"action": "copy_photos", "caption": "", "folder": "Vacanze"}\n'
    'salva le foto dei fiori nella cartella Giardino -> {"action": "copy_photos", "caption": "flowers", "folder": "Giardino"}\n'
    'prendi tutte le foto di Parigi e mettimele in una cartella Parigi -> {"action": "copy_photos", "caption": "Paris", "folder": "Parigi"}\n'
    'trovami sul telefono le foto del lago -> {"action": "find_photos", "caption": "a lake", "folder": ""}\n'
    'trovami le foto dal 20 maggio al 20 luglio -> {"action": "find_photos", "caption": "", "folder": ""}\n'
    'le foto del mare di agosto 2024 -> {"action": "find_photos", "caption": "the sea", "folder": ""}\n'
    'prendi dal telefono le foto della neve e salvale sul computer nella cartella Neve -> {"action": "copy_photos", "caption": "snow", "folder": "Neve"}\n'
    'ripensandoci, rimettile dove erano -> {"action": "undo", "caption": "", "folder": ""}\n'
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

NO_MODEL = "Non trovo nessun modello locale. Controlla che Ollama sia acceso e che ci sia almeno un modello installato."
NO_PHOTOS = "Non ho ancora nessuna foto in cui cercare: metti delle foto nella cartella che mi hai indicato."
UNCLEAR = "Non ho capito cosa cercare nelle foto. Prova a dirmelo con altre parole."
WHICH_ONES = "Dimmi prima quali foto: cercale, e poi dimmi cosa farne."
NONE_LIKE_THAT = "Non ho trovato foto così, quindi non tocco niente."
NOTHING_TO_UNDO = "Non c'è niente da annullare: non ho ancora spostato né copiato nulla."
READ_ONLY = "La cartella delle foto mi è stata data in sola lettura: posso cercare, ma non spostare né copiare."
NO_PHONE = "Non c'è nessun telefono collegato. Collegane uno dal pannello, alla voce «Telefono»."
PHONE_EMPTY = "Il telefono è collegato, ma non mi ha ancora mandato le sue foto: apri Regista sul telefono e lascialo finire."
PHONE_ONLY_COPIES = "Dal telefono per ora posso solo copiare le foto sul computer: non le cancello."


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
    copies = "quella copia" if count == 1 else "quelle copie"
    if entry["kind"] == "receive":
        return f"L'ultima modifica è stata copiare {_photos(count)} dal telefono nella cartella «{entry.get('folder', '')}». Tolgo {copies}? Sul telefono le foto restano."
    return f"L'ultima modifica è stata copiare {_photos(count)} nella cartella «{entry.get('folder', '')}». Tolgo {copies}? Gli originali non vengono toccati."


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
    else:
        still = "Sul telefono le foto ci sono ancora." if result["undid"] == "receive" else "Gli originali sono al loro posto."
        text = f"Annullato: ho tolto {'la copia' if count == 1 else f'le {count} copie'} dalla cartella «{result['folder']}». {still}"
        memory = f'The change was undone: {count} copies were removed from the folder "{result["folder"]}".'
    if stuck := result.get("failed"):
        text += f" {_photos(stuck).capitalize()} non sono riuscito a spostarl{'a' if stuck == 1 else 'e'}: chiedimelo di nuovo tra poco."
    return text, memory


def asked_in_words(count: int, folder: str) -> tuple[str, str]:
    """What is said when a phone has been asked for pictures and they have not arrived yet."""
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


def _searched(caption: str, phone: bool, when: tuple | None) -> str:
    """A search as the model will remember it: in English, with what was looked for, where and of which days."""
    what = f' for "{caption}"' if caption else ""
    taken = f" taken from {when[0]} to {when[1]}" if when else ""
    return f'Searched the photos{" on the phone" if phone else ""}{what}{taken}'


def propose(decision: dict, photos, actions, selection: list[str], phones=None, phone: bool = False, when: tuple | None = None) -> dict:
    """What a request to change the pictures becomes: words, and a proposal for the user to confirm.

    Nothing is touched here. `selection` is the pictures the user is looking at, by their
    short names: they are what "these" means. `phone` says that the request names the
    phone as the place of the pictures.
    """
    period = period_in_words(when) if when else ""

    def only(text: str, memory: str, searched: str = "") -> dict:
        return {"text": text, "memory": memory, "proposal": None, "searched": searched, "period": period if searched or when else ""}

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
        return {"text": undo_proposed_in_words(last), "memory": memory, "proposal": proposal, "searched": "", "period": ""}

    kind = "trash" if decision["action"] == "trash_photos" else "copy"
    caption, folder = decision["caption"], ""
    # the pictures are on the phone if the request says so, or if "these" are pictures of the phone
    away = phone or (not caption and not when and bool(selection) and all(on_phone(identifier) for identifier in selection))
    if away:
        if phones is None or not phones.devices:
            return only(NO_PHONE, "No phone is connected.")
        if kind == "trash":
            return only(PHONE_ONLY_COPIES, "The user asked to delete photos on the phone: that cannot be done yet.")
        if not phones.photos:
            return only(PHONE_EMPTY, "The phone has not sent its photos yet.")
        kind = "fetch"
    if kind != "trash":
        try:
            folder = collection_name(decision["folder"])
        except Refused:
            pass  # no usable name: the proposal is made all the same, and the page asks for the name
    if caption or when:
        # the message says which pictures, by what they show or by when they were taken:
        # only the ones the search is sure about are proposed
        result = (phones if away else photos).search(caption, limit=MOST, period=when)
        chosen, every = result["sure"], result["matching"]
        if not chosen:
            return only(NONE_LIKE_THAT, f"{_searched(caption, away, when)}: none found, so nothing was proposed.", caption)
    else:
        if away:
            known = {photo["id"]: photo["name"] for photo in phones.photos}
        else:
            known = {photo["id"]: photo["path"].rsplit("/", 1)[-1] for photo in photos.photos}
        chosen = [{"id": identifier, "name": known[identifier]} for identifier in dict.fromkeys(selection) if identifier in known][:MOST]
        every = len(chosen)
        if not chosen:
            return only(WHICH_ONES, "No photos were chosen, so nothing was proposed.")

    into = f'into the folder "{folder}"' if folder else "into a folder that has no name yet"
    what = {"trash": "move them to the trash", "copy": f"copy them {into}", "fetch": f"copy them from the phone to the computer, {into}"}[kind]
    # with the caption, so that the next request can build on this search too
    searched = f"{_searched(caption, away, when)}: {every} found. " if caption or when else ""
    return {
        "text": proposed_in_words(kind, len(chosen), folder, every),
        # nothing has changed yet, and the model must not think it has
        "memory": f"{searched}Proposed to {what} ({len(chosen)} photos). Nothing was done: the user must confirm.",
        "proposal": {"action": kind, "folder": folder, "photos": [{"id": photo["id"], "name": photo["name"]} for photo in chosen]},
        "searched": caption,
        "period": period if caption or when else "",
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
                selection: list[str] | None = None, phones=None):
    """One reply as a stream of events, so that the page can show it while it happens.

    "start" says which models are at work, "step" and "photos" carry a search and what it
    found, "proposal" a change that waits for the user's yes, "text" the words, and "done"
    closes with what to remember of this turn.
    """
    started = time.perf_counter()
    director = catalog.pick("tools", models, machine, tests)
    writer = catalog.pick("chat", models, machine, tests, wanted)
    if writer is None:
        yield {"type": "text", "text": NO_MODEL}
        yield {"type": "done", "model": "", "seconds": 0, "memory": NO_MODEL}
        return
    loaded = {model["name"] for model in models if model["loaded"]}
    yield {"type": "start", "director": director, "writer": writer, "loading": (director or writer) not in loaded}

    # without a model that can direct, the app can still talk
    decision = await decide(director, history) if director else {"action": "answer", "caption": "", "folder": ""}
    # the place is not something a picture shows: out of the caption, whatever the model left in it
    decision["caption"] = re.sub(r"\s+", " ", PLACE_WORDS.sub(" ", decision["caption"])).strip()
    asked = next((str(message.get("content", "")) for message in reversed(history) if message.get("role") == "user"), "")
    # The period a request names is read here, in its words, and not asked to the model (period.py).
    # And a picture does not show its date: what the model left of it in the caption comes out.
    when = read_period(asked)
    if when:
        decision["caption"] = without_time(decision["caption"])
    period = period_in_words(when) if when else ""
    action, caption = decision["action"], decision["caption"]
    # on the phone when the request says so; and when it names no place, where the pictures on screen are
    looking_there = bool(selection) and all(on_phone(identifier) for identifier in selection)
    # "salvale sul computer" names where pictures go, not where they are: only a search is moved by it
    elsewhere = action in ("find_photos", "count_photos") and bool(ON_COMPUTER.search(asked))
    phone = phones is not None and (bool(ON_PHONE.search(asked)) or (looking_there and not elsewhere))

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
        place = "phone" if phone else "computer"
        yield {"type": "step", "tool": "find_photos", "arguments": {"description": caption, "place": place, "period": period}}
        result = await asyncio.to_thread((phones if phone else photos).search, caption, 60, when)
        result["partial"] = False if phone else photos.state["running"]
        yield {"type": "photos", "description": caption, "place": place, **result}
        yield {"type": "text", "text": found_in_words(result, phone, period, bool(caption))}
        # in English and with the caption, so that "only the black ones" can build on it
        yield done(director, f'{_searched(caption, phone, when)}: {result["matching"]} found, {len(result["maybe"])} uncertain.')
        return

    if action in CHANGES and actions is not None:
        plan = await asyncio.to_thread(propose, decision, photos, actions, selection or [], phones, phone, when)
        if plan["searched"] or plan["period"]:
            yield {"type": "step", "tool": "find_photos", "arguments": {"description": plan["searched"], "place": "phone" if phone else "computer", "period": plan["period"]}}
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
