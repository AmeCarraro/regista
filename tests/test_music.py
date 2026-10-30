"""The songs of the music folder: what each file says of itself, the list, and the doors they are listened through."""
import hashlib
import struct

import pytest

import main
from music import Music, tags
from test_door import a_phone, client, home, let_in  # noqa: F401 - home is a fixture


def frame(name: bytes, words: str, how: int = 3) -> bytes:
    """An ID3 2.3 text frame: its name, its size, two bytes of flags, how the words are written, the words."""
    body = bytes([how]) + words.encode({0: "latin-1", 1: "utf-16", 3: "utf-8"}[how])
    return name + struct.pack(">I", len(body)) + b"\x00\x00" + body


def id3(*frames: bytes) -> bytes:
    tag = b"".join(frames) + b"\x00" * 20
    size = len(tag)
    return b"ID3\x03\x00\x00" + bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]) + tag


def comments(**said: str) -> bytes:
    """Vorbis comments, as FLAC, Ogg and Opus keep them."""
    lines = [f"{key.upper()}={value}".encode() for key, value in said.items()]
    return struct.pack("<I", 6) + b"Regist" + struct.pack("<I", len(lines)) + b"".join(struct.pack("<I", len(line)) + line for line in lines)


def atom(name: bytes, content: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(content), name) + content


def m4a(**said: str) -> bytes:
    names = {"title": b"\xa9nam", "artist": b"\xa9ART", "album": b"\xa9alb"}
    items = b"".join(atom(names[key], atom(b"data", b"\x00\x00\x00\x01\x00\x00\x00\x00" + value.encode())) for key, value in said.items())
    # the words after the sound, as many programs write them
    return atom(b"ftyp", b"M4A \x00\x00\x00\x00") + atom(b"mdat", b"\x00" * 5000) + atom(b"moov", atom(b"udta", atom(b"meta", b"\x00\x00\x00\x00" + atom(b"ilst", items))))


@pytest.fixture
def folder(tmp_path):
    """A music folder as a person keeps one: some songs at the top, some in folders inside folders."""
    songs = tmp_path / "Musica"
    (songs / "Mina" / "Studio Uno").mkdir(parents=True)
    (songs / "Varie").mkdir()
    (songs / "volare.mp3").write_bytes(id3(frame(b"TIT2", "Nel blu dipinto di blu"), frame(b"TPE1", "Domenico Modugno", 1), frame(b"TALB", "Sanremo 1958")) + b"\xff\xfb" * 500)
    old = b"TAG" + b"Azzurro".ljust(30, b"\x00") + b"Paolo Conte".ljust(30, b"\x00") + b"Azzurro".ljust(30, b"\x00") + b"\x00" * 35
    (songs / "Varie" / "azzurro.mp3").write_bytes(b"\xff\xfb" * 500 + old)
    flac = b"fLaC" + bytes([0]) + (34).to_bytes(3, "big") + b"\x00" * 34
    block = comments(title="Se telefonando", artist="Mina", album="Studio Uno")
    (songs / "Mina" / "Studio Uno" / "telefonando.flac").write_bytes(flac + bytes([0x84]) + len(block).to_bytes(3, "big") + block)
    (songs / "Varie" / "estate.ogg").write_bytes(b"OggS" + b"\x00" * 50 + b"\x03vorbis" + comments(title="Estate", artist="Bruno Martino"))
    (songs / "Varie" / "caruso.m4a").write_bytes(m4a(title="Caruso", artist="Lucio Dalla"))
    (songs / "Mina" / "Studio Uno" / "07 - Una canzone senza nome.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    (songs / "Mina" / "copertina.jpg").write_bytes(b"not a song")
    return songs


def test_each_file_says_its_title_artist_and_album_in_its_own_way(folder):
    assert tags(folder / "volare.mp3") == {"title": "Nel blu dipinto di blu", "artist": "Domenico Modugno", "album": "Sanremo 1958"}
    assert tags(folder / "Varie" / "azzurro.mp3") == {"title": "Azzurro", "artist": "Paolo Conte", "album": "Azzurro"}
    assert tags(folder / "Mina" / "Studio Uno" / "telefonando.flac") == {"title": "Se telefonando", "artist": "Mina", "album": "Studio Uno"}
    assert tags(folder / "Varie" / "estate.ogg") == {"title": "Estate", "artist": "Bruno Martino"}
    assert tags(folder / "Varie" / "caruso.m4a") == {"title": "Caruso", "artist": "Lucio Dalla"}
    # a file that cannot be read says nothing, and breaks nothing
    (folder / "rotto.flac").write_bytes(b"fLaC\x84\xff\xff\xff")
    assert tags(folder / "rotto.flac") == {}


def test_the_songs_of_every_folder_are_listed_by_title_and_found_by_their_name(folder):
    music = Music(folder)
    songs = music.songs()

    assert [song["title"] for song in songs] == ["Azzurro", "Caruso", "Estate", "Nel blu dipinto di blu", "Se telefonando", "Una canzone senza nome"]
    # a file that says nothing is named after itself, without its number, and its folder is its album
    nameless = songs[-1]
    assert nameless["artist"] == "" and nameless["album"] == "Studio Uno" and nameless["folder"] == "Mina/Studio Uno" and nameless["kind"] == "wav"
    assert music.path(songs[0]["id"]) == folder / "Varie" / "azzurro.mp3"
    assert music.path("../../secret") is None
    # a song added later is found too, and one taken away is not
    (folder / "nuova.mp3").write_bytes(id3(frame(b"TIT2", "Nuova")))
    (folder / "volare.mp3").unlink()
    titles = [song["title"] for song in music.songs()]
    assert "Nuova" in titles and "Nel blu dipinto di blu" not in titles
    assert Music(folder / "manca").songs() == []


def test_the_songs_are_listened_to_on_this_computer_and_from_a_paired_phone(home, folder, monkeypatch):
    monkeypatch.setattr(main, "music", Music(folder))
    listed = client.get("/api/music").json()
    assert listed["folder"] == str(folder) and len(listed["songs"]) == 6
    caruso = next(song for song in listed["songs"] if song["title"] == "Caruso")

    whole = client.get(f"/api/music/{caruso['id']}")
    assert whole.content == (folder / "Varie" / "caruso.m4a").read_bytes() and whole.headers["content-type"] == "audio/mp4"
    # the page jumps within a song: it asks for a part of it
    part = client.get(f"/api/music/{caruso['id']}", headers={"Range": "bytes=0-7"})
    assert part.status_code == 206 and part.content == whole.content[:8]
    assert client.get("/api/music/nothing").status_code == 404

    phone, key, _ = let_in()
    assert len(phone.get("/phone/music", headers=key).json()["songs"]) == 6
    taken = phone.get(f"/phone/music/{caruso['id']}", headers=key)
    assert taken.content == whole.content and taken.headers["x-regista-sha256"] == hashlib.sha256(whole.content).hexdigest()
    # only a phone that was let in, and only at the door of the phones
    assert a_phone().get("/phone/music").status_code == 401
    assert client.get("/phone/music").status_code == 404


def test_a_song_sent_by_a_phone_lands_whole_in_its_own_folder_and_writes_over_nothing(home, folder, monkeypatch):
    monkeypatch.setattr(main, "music", Music(folder))
    phone, key, _ = let_in()
    song = b"ID3" + b"\x00" * 3000

    def send(name, body=song, fingerprint=None):
        headers = {**key, "X-Regista-Sha256": fingerprint or hashlib.sha256(body).hexdigest()}
        return phone.put("/phone/music/received", params={"name": name}, content=body, headers=headers)

    assert send("Canzone mia.mp3").json() == {"kept": "Dal telefono/Canzone mia.mp3"}
    assert (folder / "Dal telefono" / "Canzone mia.mp3").read_bytes() == song
    # the same name again: a name that is free, and the first stays as it was
    assert send("Canzone mia.mp3", b"ID3" + b"\x01" * 10).json() == {"kept": "Dal telefono/Canzone mia (2).mp3"}
    assert (folder / "Dal telefono" / "Canzone mia.mp3").read_bytes() == song
    # a name cannot lead out of the folder
    assert send("../../fuori.mp3").json() == {"kept": "Dal telefono/fuori.mp3"}
    # what did not arrive whole is not kept, and neither is what is not a song
    assert send("rotta.mp3", fingerprint="0" * 64).status_code == 400
    assert send("programma.exe").status_code == 400
    assert sorted(path.name for path in (folder / "Dal telefono").iterdir()) == ["Canzone mia (2).mp3", "Canzone mia.mp3", "fuori.mp3"]
    # it is a song of the computer from now on
    assert "Canzone mia" in [song["title"] for song in client.get("/api/music").json()["songs"]]
    assert a_phone().put("/phone/music/received", params={"name": "x.mp3"}, content=song).status_code == 401
    assert client.put("/phone/music/received", params={"name": "x.mp3"}, content=song).status_code == 404
