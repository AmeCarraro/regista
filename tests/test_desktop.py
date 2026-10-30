"""The program of the PC without Docker (desktop.py): its settings, what it tells the service, and the folder it may only look at."""
import json
import sys
import threading

import pytest

import desktop
from actions import READ_ONLY, Actions, Refused
from fakes import picture

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the program of the PC is for Windows")


def test_the_settings_are_what_the_installer_wrote_over_the_defaults(tmp_path):
    assert desktop.settings(tmp_path) == desktop.DEFAULTS
    (tmp_path / "settings.json").write_text(json.dumps({"photos": "D:\\Foto", "phone": True, "port": 8091, "anything": 1}), encoding="utf-8")
    chosen = desktop.settings(tmp_path)
    assert (chosen["photos"], chosen["phone"], chosen["port"], chosen["phone_port"]) == ("D:\\Foto", True, 8091, 8443)
    assert "anything" not in chosen
    # a file that cannot be read gives the defaults, not a program that does not start
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert desktop.settings(tmp_path) == desktop.DEFAULTS


def test_the_service_is_told_where_everything_is_and_opens_the_phones_door_only_on_the_home_network(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "measured", lambda: {"HOST_GPU_NAME": "", "HOST_GPU_MB": "0", "HOST_GPU_KIND": "", "HOST_RAM_MB": "16000", "HOST_CORES": "8"})
    chosen = {**desktop.DEFAULTS, "phone": True, "phone_port": 8444}

    told = desktop.environment(tmp_path, chosen, tmp_path / "foto", ["192.168.1.85"])

    assert told["INDEX_DIR"] == str(tmp_path / "index") and told["PHOTOS_DIR"] == str(tmp_path / "foto")
    assert (told["PHONE_OPEN"], told["PHONE_HOST"], told["HOST_ADDRESSES"], told["PHONE_PORT"]) == ("1", "192.168.1.85", "192.168.1.85", "8444")
    assert told["PAGE_DIR"].endswith("dist") and told["PLACES_DIR"].endswith("geonames") and told["HOST_RAM_MB"] == "16000"
    # with no phone, or no network for one, the door of the phones answers on this PC alone
    for alone in (desktop.environment(tmp_path, {**chosen, "phone": False}, tmp_path, ["192.168.1.85"]), desktop.environment(tmp_path, chosen, tmp_path, [])):
        assert (alone["PHONE_OPEN"], alone["PHONE_HOST"], alone["HOST_ADDRESSES"]) == ("0", "127.0.0.1", "")


def test_the_computer_is_measured_as_the_installer_measures_it():
    measured = desktop.measured()
    assert int(measured["HOST_RAM_MB"]) > 1000 and int(measured["HOST_CORES"]) >= 1
    assert measured["HOST_GPU_KIND"] in ("", "nvidia", "other")
    address = desktop.home_address()
    assert address == "" or (address.count(".") == 3 and not address.startswith("127."))


def test_the_door_of_the_phones_follows_the_address_the_router_gives_this_pc(monkeypatch):
    seen = iter(["192.168.1.85", "", "192.168.1.90", "192.168.1.90", "127.0.0.1", "192.168.1.91"])
    stop = threading.Event()
    moved = []

    def home_address():
        now = next(seen, None)
        if now is None:
            stop.set()
            return "192.168.1.91"
        return now

    class Service:
        @staticmethod
        def move_phone_door(before, now):
            moved.append((before, now))

    monkeypatch.setattr(desktop, "FOLLOW_EVERY", 0.001)
    monkeypatch.setattr(desktop, "home_address", home_address)
    desktop.follow(Service, "192.168.1.85", stop)

    # no network for a while, or this PC alone, is not a new address
    assert moved == [("192.168.1.85", "192.168.1.90"), ("192.168.1.90", "192.168.1.91")]


def test_a_folder_given_to_look_at_only_is_never_changed(tmp_path):
    picture(tmp_path, "a.jpg", "red")
    actions = Actions(str(tmp_path), read_only=True)

    assert not actions.writable()
    for change in (lambda: actions.trash(["a.jpg"]), lambda: actions.copy(["a.jpg"], "Rosse"), lambda: actions.albums([("Viaggio", ["a.jpg"])]),
                   lambda: actions.incoming("Dal telefono"), lambda: actions.undo()):
        with pytest.raises(Refused, match=READ_ONLY):
            change()
    assert [file.name for file in tmp_path.iterdir()] == ["a.jpg"]
