"""Reading a period of time in a request, as if today were the 12th of October 2026."""
import datetime

import pytest

import period

TODAY = datetime.date(2026, 10, 12)


def day(text):
    return datetime.date.fromisoformat(text)


@pytest.mark.parametrize("request_text, since, until", [
    # from a day to a day
    ("le foto dal 20 maggio al 20 luglio", "2026-05-20", "2026-07-20"),
    ("dal 20 maggio al 20 luglio 2024", "2024-05-20", "2024-07-20"),
    ("trovami quelle dal 1 al 15 agosto", "2026-08-01", "2026-08-15"),
    ("dall'1 agosto all'8 agosto", "2026-08-01", "2026-08-08"),
    ("tra il 3 marzo e il 9 aprile 2023", "2023-03-03", "2023-04-09"),
    ("dal 20/5 al 20/7", "2026-05-20", "2026-07-20"),
    ("dal 20/05/2024 al 20/07/2024", "2024-05-20", "2024-07-20"),
    # across the new year: the first day is in the year before
    ("dal 20 dicembre al 5 gennaio", "2025-12-20", "2026-01-05"),
    ("dal 28 dicembre 2023 al 3 gennaio 2024", "2023-12-28", "2024-01-03"),
    # no year, and this year has not got there yet: it is last year's
    ("dal 1 novembre al 15 dicembre", "2025-11-01", "2025-12-15"),
    # from a month to a month, from a year to a year
    ("da maggio a luglio", "2026-05-01", "2026-07-31"),
    ("da novembre a febbraio", "2025-11-01", "2026-02-28"),
    ("da gennaio a febbraio 2024", "2024-01-01", "2024-02-29"),
    ("dal 2019 al 2021", "2019-01-01", "2021-12-31"),
    # one day, one month, one year
    ("le foto del 15 agosto", "2026-08-15", "2026-08-15"),
    ("le foto del 25 dicembre", "2025-12-25", "2025-12-25"),
    ("quelle del 3/2/2024", "2024-02-03", "2024-02-03"),
    ("le foto di agosto", "2026-08-01", "2026-08-31"),
    ("le foto di dicembre", "2025-12-01", "2025-12-31"),
    ("foto di febbraio 2024", "2024-02-01", "2024-02-29"),
    ("le foto di agosto del 2023", "2023-08-01", "2023-08-31"),
    ("le foto del 2023", "2023-01-01", "2023-12-31"),
    ("cosa ho fotografato nel 2019?", "2019-01-01", "2019-12-31"),
    # counted from today
    ("le foto di oggi", "2026-10-12", "2026-10-12"),
    ("quelle di ieri", "2026-10-11", "2026-10-11"),
    ("le foto della settimana scorsa", "2026-10-05", "2026-10-11"),
    ("le foto di questa settimana", "2026-10-12", "2026-10-12"),
    ("le foto del mese scorso", "2026-09-01", "2026-09-30"),
    ("le foto di questo mese", "2026-10-01", "2026-10-12"),
    ("le foto dell'anno scorso", "2025-01-01", "2025-12-31"),
    ("le foto di quest'anno", "2026-01-01", "2026-10-12"),
    ("le foto degli ultimi 7 giorni", "2026-10-05", "2026-10-12"),
    ("Le Foto Dal 20 Maggio Al 20 Luglio", "2026-05-20", "2026-07-20"),
])
def test_a_period_is_read_from_the_ways_people_say_it(request_text, since, until):
    assert period.read(request_text, TODAY) == (day(since), day(until))


@pytest.mark.parametrize("request_text", [
    "trovami le foto con un cane",
    "le foto con 2 cani",
    "trovami 2000 foto",
    "da 2 giorni non trovo le foto",
    "le foto del 31 febbraio",
    "le foto di ferragosto",
    "dal mio telefono al computer",
    "",
])
def test_what_is_not_a_period_is_not_read_as_one(request_text):
    assert period.read(request_text, TODAY) is None


@pytest.mark.parametrize("since, until, words", [
    ("2026-05-20", "2026-07-20", "dal 20 maggio al 20 luglio 2026"),
    ("2025-12-20", "2026-01-05", "dal 20 dicembre 2025 al 5 gennaio 2026"),
    ("2026-08-01", "2026-08-08", "dall'1 agosto all'8 agosto 2026"),
    ("2026-08-15", "2026-08-15", "del 15 agosto 2026"),
    ("2026-10-11", "2026-10-11", "dell'11 ottobre 2026"),
    ("2024-02-01", "2024-02-29", "di febbraio 2024"),
    ("2023-01-01", "2023-12-31", "del 2023"),
])
def test_a_period_is_said_back_in_words(since, until, words):
    assert period.in_words((day(since), day(until))) == words


@pytest.mark.parametrize("caption, kept", [
    ("a dog in August 2024", "a dog"),
    ("the sea taken last year", "the sea"),
    ("photos from May 20 to July 20", ""),
    ("pictures taken between the 20th of May and July 20, 2024", ""),
    ("photos of 2023", ""),
    ("Japan", "Japan"),
    ("a dog on the beach", "a dog on the beach"),
    ("", ""),
])
def test_what_a_caption_says_about_time_is_taken_out(caption, kept):
    assert period.without_time(caption) == kept
