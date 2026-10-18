"""Reads a period of time in a request written in Italian: "dal 20 maggio al 20 luglio", "di agosto 2024", "l'estate scorsa".

It is read here, in the words of the user, and not asked to the model: a small model gets
dates wrong, and a date wrong by a year finds the wrong pictures without anyone noticing.
A way of saying a period that is not among the ones below is simply not read as one.
"""
import calendar
import datetime
import re

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_MONTH = "(" + "|".join(MONTHS) + ")"
# the seasons by the month they begin in: whole months, as weather services count them
SEASONS = {"primavera": 3, "estate": 6, "autunno": 9, "inverno": 12}
_SEASON = "(" + "|".join(SEASONS) + ")"
_DAY = r"(\d{1,2})[º°]?"
_YEAR = r"((?:19|20)\d{2})"
_FROM = r"\b(?:dal|dall['’]|da|tra il|tra l['’]|fra il|fra l['’])\s*"
_TO = r"\s+(?:al|all['’]|a|e il|e l['’]|e)\s*"

# from a day to a day, with the months by name: "dal 20 maggio al 20 luglio 2024", "dal 1 al 15 agosto"
_DAYS = re.compile(rf"{_FROM}{_DAY}(?:\s+{_MONTH})?(?:\s+{_YEAR})?{_TO}{_DAY}\s+{_MONTH}(?:\s+{_YEAR})?")
# the same in numbers: "dal 20/5 al 20/7/2024"
_NUMBERS = re.compile(rf"{_FROM}(\d{{1,2}})[/.-](\d{{1,2}})(?:[/.-](\d{{2,4}}))?{_TO}(\d{{1,2}})[/.-](\d{{1,2}})(?:[/.-](\d{{2,4}}))?")
# from a month to a month: "da maggio a luglio"
_MONTHS = re.compile(rf"\b(?:da|tra|fra)\s+{_MONTH}(?:\s+{_YEAR})?\s+(?:a|ad|e)\s+{_MONTH}(?:\s+{_YEAR})?")
# from a year to a year: "dal 2019 al 2021"
_YEARS = re.compile(rf"\b(?:dal|tra il|fra il)\s+{_YEAR}\s+(?:al|e il)\s+{_YEAR}\b")
_ONE_DAY = re.compile(rf"\b{_DAY}\s+{_MONTH}(?:\s+{_YEAR})?")
_ONE_DAY_NUMBERS = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-]((?:19|20)\d{2})\b")
_ONE_MONTH = re.compile(rf"\b{_MONTH}(?:\s+(?:del\s+)?{_YEAR})?")
_ONE_YEAR = re.compile(rf"\b(?:del|nel|dell['’]anno|anno)\s+{_YEAR}\b")
_LAST = re.compile(r"\bultim[ie]\s+(\d{1,3})\s+(giorni|settimane|mesi)\b")
# a season: "l'estate del 2024", and "l'estate scorsa", "quest'inverno", "d'estate"
_SEASON_YEAR = re.compile(rf"\b{_SEASON}\s+(?:del\s+)?{_YEAR}\b")
_ONE_SEASON = re.compile(rf"\b{_SEASON}\b")

# What a model leaves in an English caption about when the pictures were taken: "in August 2024",
# "from May 20 to July 20", "last year". A picture does not show its date, so it comes out of the caption.
_ENGLISH_MONTH = "(?:january|february|march|april|may|june|july|august|september|october|november|december)"
_ENGLISH_SEASON = "(?:spring|summer|autumn|fall|winter)"
_WHEN = re.compile(
    rf"\b(?:taken\s+)?(?:(?:in|from|during|of|since|until|to|between|and|on)\s+)?(?:the\s+)?(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?)?{_ENGLISH_MONTH}(?:\s+\d{{1,2}}(?:st|nd|rd|th)?)?(?:,?\s*(?:19|20)\d{{2}})?\b"
    r"|\b(?:taken\s+)?(?:(?:in|of|from|during|to|and)\s+)?(?:19|20)\d{2}\b"
    r"|\b(?:taken\s+)?(?:(?:from|of|in|during)\s+)?(?:the\s+)?(?:last|this|past)\s+(?:\d+\s+)?(?:years?|months?|weeks?|days?)\b"
    r"|\b(?:today|yesterday)\b"
    # a season only with a word of time: "in the summer", "last winter", "summer 2024", but "a hot spring" stays
    rf"|\b(?:taken\s+)?(?:in|during|of|from|this|last|past)\s+(?:the\s+)?(?:(?:last|this|past)\s+)?{_ENGLISH_SEASON}(?:\s+(?:of\s+)?(?:19|20)\d{{2}})?\b"
    rf"|\b{_ENGLISH_SEASON}\s+(?:of\s+)?(?:19|20)\d{{2}}\b",
    re.IGNORECASE,
)
# what can be left of a caption that was only about time: no subject in these
_FILLER = re.compile(r"\b(?:photos?|pictures?|images?|taken|from|to|of|in|on|the|a|an|and|between|during)\b", re.IGNORECASE)


def _month_end(year: int, month: int) -> datetime.date:
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


def _years_back(day: datetime.date, years: int) -> datetime.date:
    """The same day some years earlier; the 29th of February becomes the 28th."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def _season(name: str, year: int) -> tuple[datetime.date, datetime.date]:
    """A season of a year. The winter of a year is the one that ends in it: the winter of 2024 is from December 2023."""
    first = SEASONS[name]
    if first == 12:
        return datetime.date(year - 1, 12, 1), _month_end(year, 2)
    return datetime.date(year, first, 1), _month_end(year, first + 2)


def _full_year(text: str | None) -> int | None:
    if not text:
        return None
    return int(text) if len(text) == 4 else 2000 + int(text)


def _between(first: tuple, last: tuple, today: datetime.date) -> tuple[datetime.date, datetime.date]:
    """A period from (day, month, year or None) to (day, month, year or None), with the years it does not say worked out."""
    (day1, month1, year1), (day2, month2, year2) = first, last
    said = year1 is not None or year2 is not None
    year2 = year2 or year1 or today.year
    until = datetime.date(year2, month2, day2)
    since = datetime.date(year1 or year2, month1, day1)
    if since > until:
        # "dal 20 dicembre al 5 gennaio": the first day is in the year before
        since = _years_back(since, 1)
    if not said and since > today:
        # no year was said and this one has not got there yet: pictures are of the past, so it is last year's
        since, until = _years_back(since, 1), _years_back(until, 1)
    return since, until


def read(text: str, today: datetime.date | None = None) -> tuple[datetime.date, datetime.date] | None:
    """The period a request names, as (first day, last day), or None if it names none that is understood."""
    today = today or datetime.date.today()
    text = text.lower()
    try:
        if found := _DAYS.search(text):
            day1, month1, year1, day2, month2, year2 = found.groups()
            month2 = MONTHS.index(month2) + 1
            month1 = MONTHS.index(month1) + 1 if month1 else month2
            return _between((int(day1), month1, _full_year(year1)), (int(day2), month2, _full_year(year2)), today)
        if found := _NUMBERS.search(text):
            day1, month1, year1, day2, month2, year2 = found.groups()
            return _between((int(day1), int(month1), _full_year(year1)), (int(day2), int(month2), _full_year(year2)), today)
        if found := _MONTHS.search(text):
            month1, year1, month2, year2 = found.groups()
            month1, month2 = MONTHS.index(month1) + 1, MONTHS.index(month2) + 1
            # how long the last month is depends on its year, which is worked out first
            since, until = _between((1, month1, _full_year(year1)), (28, month2, _full_year(year2)), today)
            return since, _month_end(until.year, until.month)
        if found := _YEARS.search(text):
            first, last = sorted(int(year) for year in found.groups())
            return datetime.date(first, 1, 1), datetime.date(last, 12, 31)
        if found := _SEASON_YEAR.search(text):
            return _season(found.group(1), int(found.group(2)))
        if found := _ONE_SEASON.search(text):
            name = found.group(1)
            if re.search(r"\b(?:anno scorso|scorso anno)\b", text):
                return _season(name, today.year - 1)
            # "l'estate scorsa" is the last one that is over; "quest'estate" and "d'estate", the last one that has begun
            over = re.search(r"\b(?:scors|passat)[ao]\b", text)
            for year in (today.year + 1, today.year, today.year - 1):
                since, until = _season(name, year)
                if (until < today) if over else (since <= today):
                    return since, until

        monday = today - datetime.timedelta(days=today.weekday())
        if re.search(r"\bl['’]altro ?ieri\b", text):
            return (today - datetime.timedelta(days=2),) * 2
        if re.search(r"\bieri\b", text):
            return (today - datetime.timedelta(days=1),) * 2
        if re.search(r"\boggi\b", text):
            return today, today
        if re.search(r"\b(?:settimana scorsa|scorsa settimana)\b", text):
            return monday - datetime.timedelta(days=7), monday - datetime.timedelta(days=1)
        if re.search(r"\bquesta settimana\b", text):
            return monday, today
        if re.search(r"\b(?:mese scorso|scorso mese)\b", text):
            before = today.replace(day=1) - datetime.timedelta(days=1)
            return before.replace(day=1), before
        if re.search(r"\bquesto mese\b", text):
            return today.replace(day=1), today
        if re.search(r"\b(?:anno scorso|scorso anno)\b", text):
            return datetime.date(today.year - 1, 1, 1), datetime.date(today.year - 1, 12, 31)
        if re.search(r"\bquest['’] ?anno\b", text):
            return datetime.date(today.year, 1, 1), today
        if found := _LAST.search(text):
            days = int(found.group(1)) * {"giorni": 1, "settimane": 7, "mesi": 30}[found.group(2)]
            return today - datetime.timedelta(days=days), today

        if found := _ONE_DAY.search(text):
            day, month, year = found.groups()
            one = datetime.date(_full_year(year) or today.year, MONTHS.index(month) + 1, int(day))
            if not year and one > today:
                one = _years_back(one, 1)
            return one, one
        if found := _ONE_DAY_NUMBERS.search(text):
            day, month, year = found.groups()
            one = datetime.date(int(year), int(month), int(day))
            return one, one
        if found := _ONE_MONTH.search(text):
            month, year = found.groups()
            month = MONTHS.index(month) + 1
            # a month that has not come yet this year is last year's
            year = _full_year(year) or (today.year if datetime.date(today.year, month, 1) <= today else today.year - 1)
            return datetime.date(year, month, 1), _month_end(year, month)
        if found := _ONE_YEAR.search(text):
            year = int(found.group(1))
            return datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    except ValueError:
        # the 31st of February and the like: not a period anyone can mean
        return None
    return None


def in_words(period: tuple[datetime.date, datetime.date]) -> str:
    """A period as it is said in Italian after "le foto": "di agosto 2024", "da giugno ad agosto 2026", "dal 20 maggio al 20 luglio 2026".

    Whole months are said as months: a season is said by the months it is made of, so that
    the user hears which ones were looked in.
    """
    since, until = period
    if since == until:
        # "dell'1", "dell'8", "dell'11": the days whose name starts with a vowel
        of = "dell'" if since.day in (1, 8, 11) else "del "
        return f"{of}{since.day} {MONTHS[since.month - 1]} {since.year}"
    if since.day == 1 and since.month == 1 and until.day == 31 and until.month == 12:
        return f"del {since.year}" if since.year == until.year else f"dal {since.year} al {until.year}"
    if since.day == 1 and until == _month_end(until.year, until.month):
        if (since.year, since.month) == (until.year, until.month):
            return f"di {MONTHS[since.month - 1]} {since.year}"
        first = MONTHS[since.month - 1] + ("" if since.year == until.year else f" {since.year}")
        last = MONTHS[until.month - 1]
        return f"da {first} {'ad' if last.startswith('a') else 'a'} {last} {until.year}"
    first = f"{since.day} {MONTHS[since.month - 1]}" + ("" if since.year == until.year else f" {since.year}")
    start = "dall'" if since.day in (1, 8, 11) else "dal "
    end = "all'" if until.day in (1, 8, 11) else "al "
    return f"{start}{first} {end}{until.day} {MONTHS[until.month - 1]} {until.year}"


def without_time(caption: str) -> str:
    """A caption with what it says about time taken out: "a dog in August 2024" is "a dog", and "photos from May" is nothing."""
    cleaned = re.sub(r"\s+", " ", _WHEN.sub(" ", caption)).strip(" ,.-")
    return cleaned if re.search(r"[a-z]", _FILLER.sub(" ", cleaned), re.IGNORECASE) else ""
