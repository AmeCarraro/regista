"""The trips the pictures tell of, and an album for each: found from where and when the pictures were taken."""
import asyncio
import datetime

from fastapi.testclient import TestClient

import main
import orchestrator
from actions import Actions
from fakes import ColourEmbedder, picture
from photos import PhotoIndex
from test_orchestrator import GRANITE, LAPTOP, Changes, proposed, said
from trips import trips

PADOVA, TOKYO, KYOTO, CAGLIARI = (45.4064, 11.8768), (35.6895, 139.6917), (35.0211, 135.7538), (39.2238, 9.1217)
PARIS, BARCELONA, ROME, VENICE, MILAN = (48.8534, 2.3488), (41.3888, 2.159), (41.8919, 12.5113), (45.4371, 12.3327), (45.4643, 9.1895)


class Names:
    """The Italian names of a few countries, as places.py gives them."""

    def country_name(self, code):
        return {"JP": "Giappone", "FR": "Francia", "ES": "Spagna", "IT": "Italia"}.get(code, code)


def taken(day, where, country="IT", region="", count=1):
    return [{"id": f"{day}-{where[0]}-{n}", "name": f"IMG_{day}_{n}.jpg", "day": day, "lat": where[0], "lon": where[1], "country": country, "region": region}
            for n in range(count)]


def days(first, count, step=1):
    start = datetime.date.fromisoformat(first)
    return [(start + datetime.timedelta(days=step * n)).isoformat() for n in range(count)]


def a_library():
    pictures = []
    # home: Padova, on many different days
    for day in days("2025-06-01", 25, step=17):
        pictures += taken(day, PADOVA, region="IT.20", count=2)
    # Venice is less than 50 km away: home too
    pictures += taken("2026-02-14", VENICE, region="IT.20", count=6)
    # Japan for a week, with a day with no pictures in the middle
    for day in ("2026-05-03", "2026-05-04", "2026-05-06", "2026-05-07"):
        pictures += taken(day, TOKYO if day < "2026-05-06" else KYOTO, country="JP", count=3)
    # Sardinia in summer
    for day in days("2025-08-10", 4):
        pictures += taken(day, CAGLIARI, region="IT.14", count=2)
    # France and then Spain over the new year
    for day in days("2025-12-28", 3):
        pictures += taken(day, PARIS, country="FR", count=2)
    for day in days("2025-12-31", 3):
        pictures += taken(day, BARCELONA, country="ES", count=2)
    # Rome twice, with a day at home in between: two trips
    pictures += taken("2026-03-01", ROME, region="IT.07", count=5)
    pictures += taken("2026-03-02", PADOVA, region="IT.20", count=1)
    pictures += taken("2026-03-03", ROME, region="IT.07", count=5)
    # Milan for an afternoon, three pictures: not enough for an album
    pictures += taken("2026-04-11", MILAN, region="IT.09", count=3)
    # a picture with no position, on a day of a trip: where it was taken is not known
    pictures.append({"id": "screenshot", "name": "screenshot.png", "day": "2026-05-04", "lat": None, "lon": None, "country": "", "region": ""})
    return pictures


def test_the_trips_are_the_runs_of_days_away_from_home_named_where_and_when():
    found = trips(a_library(), Names())

    assert [(trip["name"], len(trip["photos"])) for trip in found] == [
        ("Giappone, maggio 2026", 12),
        ("Lazio, marzo 2026 (2)", 5),
        ("Lazio, marzo 2026", 5),
        ("Francia e Spagna, dicembre 2025-gennaio 2026", 12),
        ("Sardegna, agosto 2025", 8),
    ]
    assert (found[0]["first"], found[0]["last"]) == ("2026-05-03", "2026-05-07")
    assert "screenshot" not in {photo["id"] for trip in found for photo in trip["photos"]}


def test_with_no_positions_there_are_no_trips():
    assert trips([{"id": "a", "name": "a.jpg", "day": "2026-01-01", "lat": None, "lon": None}], Names()) == []


class Library:
    """A picture index that only knows its trips."""

    def __init__(self, found):
        self.photos = [{"id": "x"}]
        self.found = found

    def trips(self):
        return self.found


def ask(text, photos, actions=None):
    async def collect():
        return [event async for event in orchestrator.reply([{"role": "user", "content": text}], "auto", [GRANITE], LAPTOP, {}, photos, actions, [], None)]

    return asyncio.run(collect())


def test_an_album_for_each_trip_is_proposed_with_no_model(monkeypatch):
    monkeypatch.setattr(orchestrator, "decide", None)
    found = trips(a_library(), Names())

    events = ask("fammi gli album dei viaggi", Library(found), Changes())

    plan = proposed(events)
    assert plan["action"] == "albums" and len(plan["albums"]) == 5
    assert plan["albums"][0] == {"folder": "Giappone, maggio 2026", "ids": [photo["id"] for photo in found[0]["photos"]]}
    assert len(plan["photos"]) == 42
    assert said(events).startswith("Ho trovato 5 viaggi, dal più recente: «Giappone, maggio 2026» (12 foto), «Lazio, marzo 2026 (2)» (5 foto),")
    assert ask("fammi gli album dei viaggi", Library([]), Changes())[-2]["text"] == orchestrator.NO_TRIPS


def test_a_request_for_trip_albums_is_told_from_others():
    for text in ("fammi gli album dei viaggi", "organizza le foto per viaggio", "crea un album per ogni viaggio", "make trip albums"):
        assert orchestrator.ALBUMS.search(text), text
    for text in ("le foto dei viaggi", "trovami le foto del viaggio in Giappone", "copia le foto del mare in un album"):
        assert not orchestrator.ALBUMS.search(text), text


def test_the_albums_are_made_as_one_change_and_taken_back_as_one(tmp_path, monkeypatch):
    folder = tmp_path / "foto"
    picture(folder, "tokyo.jpg", "red")
    picture(folder, "kyoto.jpg", "blue")
    picture(folder / "estate", "poetto.jpg", "green")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    monkeypatch.setattr(main, "photos", index)
    monkeypatch.setattr(main, "actions", Actions(str(folder)))
    monkeypatch.setattr(main, "read_photos", index.build)
    client = TestClient(main.app, base_url="http://127.0.0.1:8090")
    named = {photo["path"]: photo["id"] for photo in index.photos}

    done = client.post("/api/actions/albums", json={"albums": [
        {"folder": "Giappone, maggio 2026", "ids": [named["tokyo.jpg"], named["kyoto.jpg"]]},
        {"folder": "Sardegna, agosto 2025", "ids": [named["estate/poetto.jpg"], "000000000000"]},
    ]}).json()

    assert done["text"] == "Fatto: 3 foto copiate in 2 album, in Raccolte. 1 foto non c'era più."
    assert (folder / "Raccolte" / "Giappone, maggio 2026" / "kyoto.jpg").exists() and (folder / "Raccolte" / "Sardegna, agosto 2025" / "poetto.jpg").exists()
    assert (folder / "tokyo.jpg").exists() and len(index.photos) == 3
    assert client.get("/api/actions").json()["last"]["kind"] == "albums"

    back = client.post("/api/actions/undo", json={}).json()

    assert back["text"] == "Annullato: ho tolto le 3 copie dagli album dei viaggi. Gli originali sono al loro posto."
    assert not (folder / "Raccolte" / "Giappone, maggio 2026").exists() and (folder / "tokyo.jpg").exists()
    # nothing that is not an album of pictures the service knows
    assert client.post("/api/actions/albums", json={"albums": [{"folder": "../fuori", "ids": [named["tokyo.jpg"]]}]}).json()["count"] == 1
    assert client.post("/api/actions/albums", json={"albums": []}).status_code == 422
