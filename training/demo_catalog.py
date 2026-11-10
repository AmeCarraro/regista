"""Try the exported command model with a small catalog of fictional photos."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from command_model import CommandModel
from command_demo import GALLERY
from tags import Tags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("request")
    parser.add_argument("--select", nargs="+", choices=GALLERY, default=[])
    parser.add_argument("--catalog", type=Path, default=Path("build/demo-tags.sqlite"))
    args = parser.parse_args()

    command = CommandModel(args.bundle).ask(args.request)
    intent, slots = command["intent"], command["slots"]
    catalog = Tags(args.catalog)
    if intent == "search_photos":
        found = [GALLERY[identifier] for identifier in catalog.find(slots["tag"]) if identifier in GALLERY]
        print(f"Foto con il tag «{slots['tag']}»: {', '.join(found) or 'nessuna'}")
    elif intent in ("add_tag", "remove_tag"):
        if not args.select:
            print("Quali foto vuoi selezionare? Usa --select 1 2 o 3.")
            return
        tag = slots["tag"]
        selection = list(dict.fromkeys(args.select))
        verb = "Aggiungo" if intent == "add_tag" else "Tolgo"
        print(f"{verb} il tag «{tag}» per {', '.join(GALLERY[identifier] for identifier in selection)}.")
        if input("Confermi? [s/N] ").strip().casefold() in ("s", "sì", "si"):
            change = catalog.add if intent == "add_tag" else catalog.remove
            print(f"Foto aggiornate: {len(change(tag, selection))}.")
        else:
            print("Modifica annullata.")
    elif intent == "play_song":
        print(f"Brano riconosciuto: {slots['title']}. La demo contiene solo foto.")
    else:
        print("Puoi specificare quale foto o quale tag intendi?")


if __name__ == "__main__":
    main()
