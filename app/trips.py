"""The trips the pictures tell of, found from where and when they were taken.

Home is where the pictures of the most different days were taken. A trip is a run of days with
pictures taken more than AWAY km from there, with no day at home in between and no more than GAP
days without pictures; it is named after where it was, as Italians say it, and when:
"Giappone, maggio 2026", "Sardegna, agosto 2025". A picture with no position in it, or with no
day, is in no trip: where it was taken is not known.
"""
import datetime
import math
from bisect import bisect_right
from collections import Counter, defaultdict

import numpy as np

from period import MONTHS
from places import REGIONS

# how far from home a picture is taken on a trip, in kilometres
AWAY = 50
# the most days with no pictures inside one trip
GAP = 3
# the fewest pictures a trip must have to get an album
FEWEST = 5


def _kilometres(latitude: float, longitude: float, latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    """Kilometres from one point to many, all in degrees, along the surface of the Earth."""
    here, there = math.radians(latitude), np.radians(latitudes)
    across = np.radians(longitudes) - math.radians(longitude)
    half = np.sin((there - here) / 2) ** 2 + math.cos(here) * np.cos(there) * np.sin(across / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(half))


def _when(first: str, last: str) -> str:
    """The months of a trip: "maggio 2026", "maggio-giugno 2026", "dicembre 2025-gennaio 2026"."""
    since, until = datetime.date.fromisoformat(first), datetime.date.fromisoformat(last)
    if (since.year, since.month) == (until.year, until.month):
        return f"{MONTHS[since.month - 1]} {since.year}"
    if since.year == until.year:
        return f"{MONTHS[since.month - 1]}-{MONTHS[until.month - 1]} {since.year}"
    return f"{MONTHS[since.month - 1]} {since.year}-{MONTHS[until.month - 1]} {until.year}"


def _where(pictures: list[dict], home_country: str, places) -> str:
    """Where a trip was: the region, in the country of home and when it is Italy, and the country otherwise; two when it was in two."""
    def named(picture: dict) -> str:
        if picture.get("country") == home_country and picture.get("region") in REGIONS:
            return REGIONS[picture["region"]][0]
        code = picture.get("country", "")
        return places.country_name(code) if places is not None and code else code or "Altrove"

    counted = Counter(named(picture) for picture in pictures).most_common(2)
    if len(counted) > 1 and counted[1][1] * 4 >= len(pictures):
        return f"{counted[0][0]} e {counted[1][0]}"
    return counted[0][0]


def trips(entries: list[dict], places=None) -> list[dict]:
    """The trips among some pictures, the latest first: {"name", "first", "last", "photos"}, the pictures as given."""
    placed = [entry for entry in entries if entry.get("lat") is not None and entry.get("lon") is not None and entry.get("day")]
    if not placed:
        return []
    # home: the square of about 25 km where the pictures of the most different days were taken
    days_in: dict[tuple, set] = defaultdict(set)
    for entry in placed:
        days_in[(round(entry["lat"] * 4), round(entry["lon"] * 4))].add(entry["day"])
    square = max(days_in, key=lambda cell: (len(days_in[cell]), cell))
    there = [entry for entry in placed if (round(entry["lat"] * 4), round(entry["lon"] * 4)) == square]
    home = (sum(entry["lat"] for entry in there) / len(there), sum(entry["lon"] for entry in there) / len(there))
    home_country = Counter(entry.get("country", "") for entry in there).most_common(1)[0][0]

    far = _kilometres(home[0], home[1], np.array([entry["lat"] for entry in placed]), np.array([entry["lon"] for entry in placed])) > AWAY
    away = [entry for entry, out in zip(placed, far) if out]
    away_days = sorted({entry["day"] for entry in away})
    # a day with pictures only at home ends a trip, however short the time without pictures
    home_days = sorted({entry["day"] for entry, out in zip(placed, far) if not out} - set(away_days))

    runs: list[list[str]] = []
    for day in away_days:
        if runs:
            before = runs[-1][-1]
            gap = (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(before)).days - 1
            back_home = bisect_right(home_days, before) < len(home_days) and home_days[bisect_right(home_days, before)] < day
            if gap <= GAP and not back_home:
                runs[-1].append(day)
                continue
        runs.append([day])

    found = []
    for run in runs:
        days = set(run)
        pictures = [entry for entry in away if entry["day"] in days]
        if len(pictures) < FEWEST:
            continue
        name = f"{_where(pictures, home_country, places)}, {_when(run[0], run[-1])}"
        found.append({"name": name, "first": run[0], "last": run[-1], "photos": sorted(pictures, key=lambda entry: (entry["day"], entry.get("name", "")))})
    found.sort(key=lambda trip: trip["first"], reverse=True)
    # two trips of the same name, in the same months: the later one gets a number, as a second folder would
    seen: Counter = Counter()
    for trip in reversed(found):
        seen[trip["name"]] += 1
        if seen[trip["name"]] > 1:
            trip["name"] = f"{trip['name']} ({seen[trip['name']]})"
    return found
