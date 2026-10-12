"""Pictures found by where they were taken, with a table of five cities in place of the world's."""
import asyncio
import zipfile

import pytest
from PIL import Image

import orchestrator
from fakes import COLOURS, ColourEmbedder, shot
from phone import Phones
from photos import PhotoIndex
from places import Places, position_of
from test_orchestrator import Changes, form, proposed, said, script

TOKYO, KYOTO, PARIS, NICE, ROME = (35.6895, 139.6917), (35.0211, 135.7538), (48.8534, 2.3488), (43.7031, 7.2661), (41.8919, 12.5113)


def row(name, other_names, position, country, people):
    """A city as the table of GeoNames writes it: nineteen columns, of which this app reads seven."""
    cells = [""] * 19
    cells[1], cells[2], cells[3], cells[4], cells[5], cells[8], cells[14] = name, name, other_names, str(position[0]), str(position[1]), country, str(people)
    return "\t".join(cells)


@pytest.fixture
def places(tmp_path):
    folder = tmp_path / "geonames"
    folder.mkdir()
    cities = [
        row("Tokyo", "Tokio,TYO", TOKYO, "JP", 9_700_000),
        row("Kyoto", "Kioto", KYOTO, "JP", 1_400_000),
        row("Paris", "Parigi,PAR", PARIS, "FR", 2_100_000),
        row("Nice", "Nizza", NICE, "FR", 340_000),
        row("Rome", "Roma", ROME, "IT", 2_800_000),
        # a village with the name of a capital does not take its place
        row("Paris", "", (33.66, -95.55), "US", 25_000),
        # nor does a large town that someone, somewhere, also calls by the name of a smaller city
        row("Venice", "Venezia", (45.4371, 12.3327), "IT", 51_000),
        row("Dayton", "Venice,Daytona", (39.7589, -84.1916), "US", 140_000),
    ]
    with zipfile.ZipFile(folder / "cities15000.zip", "w") as packed:
        packed.writestr("cities15000.txt", "\n".join(cities))
    countries = "# comments at the top\nJP\tJPN\t392\tJA\tJapan\nFR\tFRA\t250\tFR\tFrance\nIT\tITA\t380\tIT\tItaly\nTR\tTUR\t792\tTU\tTurkey\n"
    (folder / "countryInfo.txt").write_text(countries, encoding="utf-8")
    return Places(str(folder))


def taken_at(folder, name, colour, position=None):
    """A picture with the place it was taken written in it, as a camera does: degrees, minutes and seconds, and the side of the world."""
    folder.mkdir(parents=True, exist_ok=True)
    written = Image.Exif()
    if position:
        def parts(value):
            value = abs(value)
            return (int(value), int(value * 60 % 60), round(value * 3600 % 60, 2))

        written.get_ifd(0x8825).update({1: "N" if position[0] >= 0 else "S", 2: parts(position[0]), 3: "E" if position[1] >= 0 else "W", 4: parts(position[1])})
    Image.new("RGB", (64, 48), COLOURS[colour]).save(folder / name, exif=written)


def test_the_place_of_a_picture_is_read_from_what_its_camera_wrote(tmp_path):
    taken_at(tmp_path, "tokyo.jpg", "red", TOKYO)
    taken_at(tmp_path, "sydney.jpg", "red", (-33.8688, 151.2093))
    taken_at(tmp_path, "new-york.jpg", "red", (40.7128, -74.0060))
    taken_at(tmp_path, "nowhere.jpg", "red")
    taken_at(tmp_path, "unknown.jpg", "red", (0.0, 0.0))

    assert position_of(tmp_path / "tokyo.jpg") == pytest.approx(TOKYO, abs=0.001)
    # south and west are the other side of the numbers
    assert position_of(tmp_path / "sydney.jpg") == pytest.approx((-33.8688, 151.2093), abs=0.001)
    assert position_of(tmp_path / "new-york.jpg") == pytest.approx((40.7128, -74.0060), abs=0.001)
    assert position_of(tmp_path / "nowhere.jpg") is None and position_of(tmp_path / "unknown.jpg") is None


def test_a_position_is_in_the_country_of_the_nearest_city(places):
    assert places.of((35.36, 138.73)) == "JP"      # Mount Fuji: Tokyo is the nearest
    assert places.of((45.44, 12.33)) == "IT"       # Venice: Rome is nearer than Nice
    assert places.of(None) == ""


@pytest.mark.parametrize("caption, asked, kind, name, left", [
    ("Japan", "le foto del Giappone", "country", "Japan", ""),
    ("photos of Japan", "", "country", "Japan", ""),
    ("the sea in Japan", "", "country", "Japan", "the sea"),
    ("Tokyo", "", "city", "Tokyo", ""),
    # the name the user used is the one shown
    ("Paris", "le foto di Parigi", "city", "Parigi", ""),
    ("a dog in Kyoto", "un cane a Kioto", "city", "Kioto", "a dog"),
    ("Turkey", "", "country", "Turkey", ""),
])
def test_a_place_is_found_in_a_caption(places, caption, asked, kind, name, left):
    spot, rest = places.find(caption, asked)

    assert (spot["kind"], spot["name"], rest) == (kind, name, left)


@pytest.mark.parametrize("caption", ["a nice dog", "a turkey", "nice", "a dog in a park", "churches", "the sea", "PAR", ""])
def test_a_word_that_is_also_a_place_is_not_one_without_the_capital_of_a_name(places, caption):
    assert places.find(caption) == (None, caption)


def test_a_capital_is_the_largest_city_of_that_name(places):
    spot, _ = places.find("Paris")

    assert spot["latitude"] == pytest.approx(PARIS[0])


def test_a_city_keeps_its_own_name_against_a_larger_one_that_is_also_called_so(places):
    spot, _ = places.find("Venice", "le foto di Venezia")

    assert (spot["name"], spot["latitude"]) == ("Venezia", pytest.approx(45.4371))


def test_without_the_table_no_place_is_known(tmp_path):
    nothing = Places(str(tmp_path / "missing"))

    assert nothing.known is False and nothing.of(TOKYO) == "" and nothing.find("Japan") == (None, "Japan")


@pytest.fixture
def library(tmp_path, places):
    """Five pictures: two in Tokyo, one in Kyoto, one in Paris, one that does not say where."""
    folder = tmp_path / "foto"
    taken_at(folder, "tower.jpg", "red", TOKYO)
    taken_at(folder, "crossing.jpg", "blue", (35.6595, 139.7005))
    taken_at(folder, "temple.jpg", "red", KYOTO)
    taken_at(folder, "louvre.jpg", "blue", PARIS)
    taken_at(folder, "somewhere.jpg", "blue")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder(), places)
    index.build()
    return index


def names(result):
    return sorted(photo["name"] for photo in result["sure"])


def test_pictures_are_found_by_the_country_and_by_the_city_they_were_taken_in(library, places):
    japan, tokyo, paris = places.find("Japan")[0], places.find("Tokyo")[0], places.find("Paris")[0]

    assert names(library.search("", spot=japan)) == ["crossing.jpg", "temple.jpg", "tower.jpg"]
    # Kyoto is in Japan and far from Tokyo
    assert names(library.search("", spot=tokyo)) == ["crossing.jpg", "tower.jpg"]
    assert names(library.search("", spot=paris)) == ["louvre.jpg"]
    # with what the pictures show, too
    assert names(library.search("something red", spot=japan)) == ["temple.jpg", "tower.jpg"]
    assert library.search("", spot=places.find("Turkey")[0])["matching"] == 0


def test_the_pictures_of_a_phone_are_found_by_place_too(tmp_path, places):
    phones = Phones(str(tmp_path / "phone"), ColourEmbedder(), [], 8443, places=places)
    phones.devices.append({"id": "d1", "name": "Pixel", "key": "", "paired": "", "seen": ""})
    phones.add("d1", [
        {**shot("1", "red", name="shrine.jpg"), "lat": KYOTO[0], "lon": KYOTO[1]},
        {**shot("2", "red", name="colosseum.jpg"), "lat": ROME[0], "lon": ROME[1]},
        {**shot("3", "red", name="no-place.jpg")},
        {**shot("4", "red", name="nonsense.jpg"), "lat": 400, "lon": "east"},
    ])

    assert names(phones.search("", spot=places.find("Japan")[0])) == ["shrine.jpg"]
    assert names(phones.search("", spot=places.find("Rome")[0])) == ["colosseum.jpg"]
    assert [photo["country"] for photo in phones.photos] == ["JP", "IT", "", ""]


def test_a_picture_whose_place_the_phone_did_not_say_is_asked_for_again(tmp_path, places):
    phones = Phones(str(tmp_path / "phone"), ColourEmbedder(), [], 8443, places=places)
    phones.add("d1", [shot("1", "red")])
    assert phones.wanted("d1", [{"id": "1", "stamp": "1"}]) == []
    # as kept before places were: the day is there, where it was taken was never asked
    for noted in ("lat", "lon", "country"):
        del phones.photos[0][noted]

    assert phones.wanted("d1", [{"id": "1", "stamp": "1"}]) == ["1"]


# ---- from a request in words


def ask(text, index, places, monkeypatch, actions=None):
    models = [{"name": "granite4.1:3b", "bytes": 2.1e9, "parameters": "3.4B", "capabilities": ["completion", "tools"], "loaded": True, "gpu_share": 1.0}]
    machine = orchestrator.catalog.Hardware(gpu="RTX 3050 Ti", gpu_gb=4.0, ram_gb=16.0, cores=14)

    async def collect():
        return [event async for event in orchestrator.reply([{"role": "user", "content": text}], "auto", models, machine, {}, index, actions, [], None, places)]

    return asyncio.run(collect())


def test_a_request_for_a_place_finds_the_pictures_taken_there(library, places, monkeypatch):
    script(monkeypatch, [form("find_photos", "Japan")])

    events = ask("trovami le foto del Giappone", library, places, monkeypatch)

    assert events[1]["arguments"] == {"description": "", "place": "computer", "period": "", "spot": "in Japan"}
    assert names(events[2]) == ["crossing.jpg", "temple.jpg", "tower.jpg"]
    assert said(events) == "Ho trovato 3 foto scattate in Japan."
    assert events[-1]["memory"] == "Searched the photos taken in Japan: 3 found, 0 uncertain."


def test_a_place_and_what_the_pictures_show_work_together(library, places, monkeypatch):
    script(monkeypatch, [form("find_photos", "something red in Tokyo")])

    events = ask("le cose rosse a Tokio", library, places, monkeypatch)

    assert events[1]["arguments"] == {"description": "something red", "place": "computer", "period": "", "spot": "a Tokio"}
    assert names(events[2]) == ["tower.jpg"] and said(events) == "Ho trovato 1 foto scattate a Tokio."


def test_when_no_picture_says_it_was_taken_there_the_ones_that_look_like_it_are_shown(library, places, monkeypatch):
    script(monkeypatch, [form("find_photos", "Turkey")])

    events = ask("le foto della Turchia", library, places, monkeypatch)

    # the search is the one there was before places were known, and the words say why
    assert events[1]["arguments"] == {"description": "Turkey", "place": "computer", "period": "", "spot": ""}
    assert said(events).startswith("Nessuna foto risulta scattata in Turkey: cerco quelle che ci somigliano. ")


def test_the_pictures_of_a_place_can_be_proposed_for_a_copy(library, places, monkeypatch):
    script(monkeypatch, [form("copy_photos", "Japan", "Giappone")])

    events = ask("prendi tutte le foto del Giappone e salvamele in una cartella Giappone", library, places, monkeypatch, actions=Changes())

    assert sorted(photo["name"] for photo in proposed(events)["photos"]) == ["crossing.jpg", "temple.jpg", "tower.jpg"]
    assert events[1]["arguments"] == {"description": "", "place": "computer", "period": "", "spot": "in Japan"}
    assert events[-1]["memory"].startswith("Searched the photos taken in Japan: 3 found. Proposed to copy them")
