"""Where a picture was taken, by name.

A camera writes in a picture where it was, as two numbers. To know that those numbers are
"Japan" or "Paris" takes a table of places: the cities of the world with their position,
from GeoNames (geonames.org, licence CC BY 4.0), kept in data/geonames. A picture belongs
to the country of the city nearest to it, and to a city when it was taken close to it.

Without the table, or for a picture with no position, nothing here applies: the app then
looks at what pictures show, as it did before.
"""
import math
import re
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

# how far from a city a picture can be and still be "of" that city, in kilometres
NEAR = 50
# The Italian regions: what GeoNames calls each (the country, then the code of the region in it),
# its names in Italian and in English, and how it is said after "scattate". The phone has the same (regions.ts).
REGIONS = {
    "IT.01": ("Abruzzo", ("abruzzo",), "in Abruzzo"),
    "IT.02": ("Basilicata", ("basilicata",), "in Basilicata"),
    "IT.03": ("Calabria", ("calabria",), "in Calabria"),
    "IT.04": ("Campania", ("campania",), "in Campania"),
    "IT.05": ("Emilia-Romagna", ("emilia-romagna", "emilia romagna", "emilia", "romagna"), "in Emilia-Romagna"),
    "IT.06": ("Friuli-Venezia Giulia", ("friuli-venezia giulia", "friuli venezia giulia", "friuli", "venezia giulia"), "in Friuli-Venezia Giulia"),
    "IT.07": ("Lazio", ("lazio", "latium"), "nel Lazio"),
    "IT.08": ("Liguria", ("liguria",), "in Liguria"),
    "IT.09": ("Lombardia", ("lombardia", "lombardy"), "in Lombardia"),
    "IT.10": ("Marche", ("marche", "the marches"), "nelle Marche"),
    "IT.11": ("Molise", ("molise",), "in Molise"),
    "IT.12": ("Piemonte", ("piemonte", "piedmont"), "in Piemonte"),
    "IT.13": ("Puglia", ("puglia", "apulia"), "in Puglia"),
    "IT.14": ("Sardegna", ("sardegna", "sardinia"), "in Sardegna"),
    "IT.15": ("Sicilia", ("sicilia", "sicily"), "in Sicilia"),
    "IT.16": ("Toscana", ("toscana", "tuscany"), "in Toscana"),
    "IT.17": ("Trentino-Alto Adige", ("trentino-alto adige", "trentino alto adige", "trentino", "alto adige", "south tyrol"), "in Trentino-Alto Adige"),
    "IT.18": ("Umbria", ("umbria",), "in Umbria"),
    "IT.19": ("Valle d'Aosta", ("valle d'aosta", "val d'aosta", "aosta valley"), "in Valle d'Aosta"),
    "IT.20": ("Veneto", ("veneto",), "in Veneto"),
}
# countries said with another word than "in": "negli Stati Uniti", "nel Regno Unito"
IN_COUNTRY = {
    "US": "negli Stati Uniti", "GB": "nel Regno Unito", "NL": "nei Paesi Bassi", "AE": "negli Emirati Arabi Uniti",
    "PH": "nelle Filippine", "MV": "nelle Maldive", "SC": "nelle Seychelles", "VA": "nella Città del Vaticano",
}
EARTH = 6371.0
# what can come before a place when it is all a caption says: "photos of Japan", "in the Netherlands"
_LEAD = re.compile(r"^(?:(?:photos?|pictures?|images?)\s+(?:of|from|in|taken in)\s+|(?:in|from|at)\s+)?(?:the\s+)?", re.IGNORECASE)
# a place at the end of a caption that also says what the pictures show: "a dog in Tokyo"
_AT_THE_END = re.compile(r"(.+?)\s+(?:in|at|from|near)\s+(?:the\s+)?(.+)")


def position_of(file: Path) -> tuple[float, float] | None:
    """Where a picture was taken, as (latitude, longitude) in degrees, if its camera wrote it."""
    try:
        with Image.open(file) as image:
            written = image.getexif().get_ifd(0x8825)
        latitude = _degrees(written.get(2), written.get(1), "S")
        longitude = _degrees(written.get(4), written.get(3), "W")
    except (OSError, ValueError, TypeError, ZeroDivisionError):
        return None
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    # 0, 0 is in the ocean: it is what a camera writes when it does not know
    return None if latitude == 0 and longitude == 0 else (round(latitude, 5), round(longitude, 5))


def _degrees(parts, side, negative: str) -> float | None:
    """Degrees, minutes and seconds as one number, negative for the south and the west."""
    if not parts or len(parts) != 3:
        return None
    value = float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
    return -value if str(side).upper().startswith(negative) else value


def _distances(latitude: float, longitude: float, latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    """Kilometres from one point to many, all in degrees, along the surface of the Earth."""
    here, there = math.radians(latitude), np.radians(latitudes)
    across = np.radians(longitudes) - math.radians(longitude)
    half = np.sin((there - here) / 2) ** 2 + math.cos(here) * np.cos(there) * np.sin(across / 2) ** 2
    return 2 * EARTH * np.arcsin(np.sqrt(half))


class Places:
    def __init__(self, folder: str):
        """Reads the table from a folder. If it is not there the object knows no place, and `known` says so."""
        self.names: list[str] = []
        self.codes: list[str] = []
        # the region of every city, as "IT.14": the country, then the code GeoNames gives the region in it
        self.regions: list[str] = []
        self.latitudes = self.longitudes = np.zeros(0)
        # a name in small letters -> the largest city called so, in any of the languages the table has
        self._cities: dict[str, int] = {}
        # the English name of a country in small letters -> (its code, its name)
        self._countries: dict[str, tuple[str, str]] = {}
        # the name of a region in small letters, in Italian or in English -> its code
        self._regions = {name: code for code, (_, names, _) in REGIONS.items() for name in names}
        # the Italian name of every country, by its code, to speak of it as Italians do
        self._italian: dict[str, str] = {}
        cities, countries = Path(folder) / "cities15000.zip", Path(folder) / "countryInfo.txt"
        if not (cities.exists() and countries.exists()):
            return

        latitudes, longitudes = [], []
        # for every name, how good the city that holds it is: its own name beats a name it is also known by
        # (Venice is Venice, though a larger town elsewhere is also called so by someone), and then the larger city wins
        best: dict[str, tuple[bool, int]] = {}
        with zipfile.ZipFile(cities) as packed:
            rows = packed.read(packed.namelist()[0]).decode("utf-8").splitlines()
        for position, row in enumerate(rows):
            # the columns, as GeoNames documents them: 1 name, 2 name in plain letters, 3 other names,
            # 4 and 5 position, 8 country, 14 inhabitants
            cells = row.split("\t")
            self.names.append(cells[1])
            self.codes.append(cells[8])
            self.regions.append(f"{cells[8]}.{cells[10]}")
            latitudes.append(float(cells[4]))
            longitudes.append(float(cells[5]))
            people = int(cells[14] or 0)
            own = {cells[1].lower(), cells[2].lower()}
            for key in own | {name.lower() for name in cells[3].split(",")}:
                # the short names in the table are mostly airport codes, and many others are in other alphabets
                if len(key) < 4 or not re.fullmatch(r"[a-zà-ÿ' .-]+", key):
                    continue
                rank = (key in own, people)
                if key not in best or rank > best[key]:
                    best[key] = rank
                    self._cities[key] = position
        self.latitudes, self.longitudes = np.array(latitudes), np.array(longitudes)
        for line in countries.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                cells = line.split("\t")
                self._countries[cells[4].lower()] = (cells[0], cells[4])
        italian = Path(folder) / "countries.tsv"
        if italian.exists():
            for line in italian.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#"):
                    code, name, english = line.split("\t")[:3]
                    self._italian[code] = name
                    # the model may write the name CLDR gives, too: "Czechia", "South Korea"
                    self._countries.setdefault(english.lower(), (code, english))

    @property
    def known(self) -> bool:
        return bool(self.names)

    def of(self, position: tuple[float, float] | None) -> str:
        """The country a position is in, as the two letters of its code: the one of the nearest city. Empty if not known."""
        return self.where(position)[0]

    def country_name(self, code: str) -> str:
        """A country as Italians write it, by its code: "Giappone". In English when that is all that is known, or the code itself."""
        if code in self._italian:
            return self._italian[code]
        return next((label for known, label in self._countries.values() if known == code), code)

    def where(self, position: tuple[float, float] | None) -> tuple[str, str]:
        """The country and the region a position is in, as ("IT", "IT.14"): those of the nearest city. Empty if not known."""
        if position is None or not self.known:
            return "", ""
        nearest = int(np.argmin(_distances(position[0], position[1], self.latitudes, self.longitudes)))
        return self.codes[nearest], self.regions[nearest]

    def find(self, caption: str, asked: str = "") -> tuple[dict | None, str]:
        """The place a caption names, and what is left of the caption without it.

        The caption is what the model wrote, in English: "Japan", "a dog in Tokyo". A place
        is taken as one only when it is written with a capital letter, as names are, and it
        is the whole caption or comes at its end after "in", "at", "from" or "near":
        "a nice dog" is not the city of Nice. `asked` is the user's own request: if it has
        the city under another name, as "Parigi" for Paris, that is the name to show.
        """
        if not self.known:
            return None, caption
        text = caption.strip()
        candidates = [(_LEAD.sub("", text), "")]
        if found := _AT_THE_END.fullmatch(text):
            candidates.append((found.group(2), found.group(1).strip()))
        for name, rest in candidates:
            if not name[:1].isupper():
                continue
            key = name.lower()
            if key in self._countries:
                code, label = self._countries[key]
                return {"kind": "country", "code": code, "name": self._italian.get(code, label)}, rest
            if key in self._regions:
                code = self._regions[key]
                return {"kind": "region", "code": code, "name": REGIONS[code][0]}, rest
            if key in self._cities:
                city = self._cities[key]
                label = next((word for word in re.findall(r"[\w'-]+", asked) if self._cities.get(word.lower()) == city), self.names[city])
                return {"kind": "city", "latitude": float(self.latitudes[city]), "longitude": float(self.longitudes[city]), "name": label}, rest
        return None, caption

    def inside(self, spot: dict, entries: list[dict]) -> list[int]:
        """The pictures taken in a spot, by their position in the list. A picture with no position is in none."""
        if spot["kind"] == "country":
            return [index for index, entry in enumerate(entries) if entry.get("country") == spot["code"]]
        if spot["kind"] == "region":
            return [index for index, entry in enumerate(entries) if entry.get("region") == spot["code"]]
        placed = [index for index, entry in enumerate(entries) if entry.get("lat") is not None]
        if not placed:
            return []
        far = _distances(spot["latitude"], spot["longitude"], np.array([entries[index]["lat"] for index in placed]), np.array([entries[index]["lon"] for index in placed]))
        return [index for index, distance in zip(placed, far) if distance <= NEAR]
