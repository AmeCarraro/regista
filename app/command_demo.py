"""Opt-in desktop demo of the command model on a fictional photo catalog."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tags import Tags


GALLERY = {"1": "Passeggiata.jpg", "2": "Stazione.jpg", "3": "Mercato.jpg"}


class RequestText(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    selection: list[str] = Field(max_length=len(GALLERY))


class TagChange(BaseModel):
    action: Literal["add_tag", "remove_tag"]
    tag: str = Field(min_length=1, max_length=500)
    ids: list[str] = Field(min_length=1, max_length=len(GALLERY))


def demo_routes(bundle: str | None, database: Path) -> APIRouter:
    router = APIRouter(prefix="/api/command-demo")

    @lru_cache(maxsize=1)
    def model():
        from command_model import CommandModel

        try:
            return CommandModel(bundle)
        except (OSError, ValueError, KeyError) as error:
            raise HTTPException(503, "Il modello della demo non si apre. Controlla il pacchetto ONNX.") from error

    def catalog():
        if not bundle:
            raise HTTPException(404, "La demo dei comandi è disattivata.")
        return Tags(database)

    def pictures(tags):
        return [{"id": identifier, "name": name, "tags": tags.for_photo(identifier)} for identifier, name in GALLERY.items()]

    def selection(ids):
        if any(identifier not in GALLERY for identifier in ids):
            raise HTTPException(422, "Scegli solo le foto della demo.")
        return list(dict.fromkeys(ids))

    @router.get("")
    def status():
        return {"available": bool(bundle), "photos": pictures(catalog()) if bundle else []}

    @router.post("/interpret")
    def interpret(body: RequestText):
        tags = catalog()
        selected = selection(body.selection)
        command = model().ask(body.text)
        intent, slots = command["intent"], command["slots"]
        message = "Puoi specificare quale foto o quale tag intendi?"
        found = proposal = None
        if intent == "search_photos":
            tag = slots["tag"]
            found = [identifier for identifier in tags.find(tag) if identifier in GALLERY]
            message = f"Foto con il tag «{tag}»: {len(found)}."
        elif intent in ("add_tag", "remove_tag"):
            if selected:
                tag = slots["tag"]
                verb = "Aggiungo" if intent == "add_tag" else "Tolgo"
                message = f"{verb} il tag «{tag}» per {len(selected)} foto."
                proposal = {"action": intent, "tag": tag, "ids": selected}
            else:
                message = "Seleziona prima le foto da modificare."
        elif intent == "play_song":
            message = f"Brano riconosciuto: {slots['title']}. La demo contiene solo foto."
        return {"message": message, "found": found, "proposal": proposal}

    @router.post("/tags")
    def change(body: TagChange):
        tags = catalog()
        selected = selection(body.ids)
        edit = tags.add if body.action == "add_tag" else tags.remove
        try:
            changed = edit(body.tag, selected)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"changed": len(changed), "photos": pictures(tags)}

    return router
