"""Regista as a program of Windows, with no Docker: what its icon starts, in the folder tools/desktop.ps1 makes.

That folder carries the official Python, signed by those who make it, and the icon starts this file with
it: Windows' Smart App Control, on in a new Windows 11, blocks a program nobody signed that it does not
know, as an .exe made here would be.

It does what run.ps1 and the container did together. It measures the computer, for the choice of the
models (catalog.py); starts Ollama if it is installed and not running, as after a restart of the PC;
starts the service on this PC's own door, 127.0.0.1, and, when a phone is used, the door of the phones
on the PC's address in the home network and nowhere else; and shows the page in a window of its own.
Closing the window stops it all.

What it works on is in settings.json, in its folder, as install.ps1 wrote it: the folder of the
pictures, whether it may only look at them, whether a phone is used, the ports. Its own data, the index
of the pictures, their small copies and the phones let in, is in the folder "index" next to it. Run from
the sources, it keeps them in %LOCALAPPDATA%\\Regista, or where --home says.

    python\\pythonw.exe app\\desktop.py      as installed
    python app\\desktop.py --home D:\\prova --photos foto --port 8091 --phone-port 8444 --no-window
"""
import argparse
import ctypes
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# the folder of the program, laid out as the repository is: app, web\dist, data\geonames, models\phone, tools
HERE = Path(__file__).resolve().parent.parent
# the app's own modules, also when Python was started isolated from the folder it runs from
sys.path.insert(0, str(HERE / "app"))
# started with pythonw.exe, as the icon does: no console, so what goes wrong is said in a small window
WINDOWED = sys.stdout is None
ICON = HERE / "tools" / "regista.ico"
DEFAULTS = {"photos": "", "read_only": False, "phone": False, "port": 8090, "phone_port": 8443, "addresses": [], "models": "", "music": ""}
# a program started from here opens no window of its own
NO_WINDOW = 0x08000000
OLLAMA = "http://127.0.0.1:11434"


def settings(home: Path) -> dict:
    """What install.ps1 wrote, over the defaults. A setting that is missing, or a file that cannot be read, gives the default."""
    try:
        written = json.loads((home / "settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        written = {}
    return {**DEFAULTS, **{key: value for key, value in (written if isinstance(written, dict) else {}).items() if key in DEFAULTS}}


def measured() -> dict:
    """The computer as tools\\computer.ps1 measures it for the installer, in the names the service reads (catalog.hardware):
    the graphics card and its memory, the memory, the processor's cores."""
    card = {"HOST_GPU_NAME": "", "HOST_GPU_MB": "0", "HOST_GPU_KIND": ""}
    try:
        lines = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout.strip().splitlines()
        name, megabytes = [part.strip() for part in lines[0].split(",")[:2]]
        card = {"HOST_GPU_NAME": name, "HOST_GPU_MB": str(round(float(megabytes))), "HOST_GPU_KIND": "nvidia"}
    except (OSError, IndexError, ValueError, subprocess.SubprocessError):
        # No NVIDIA card. Windows knows the others, and their memory: a card built into the processor has next to
        # none and is not counted. Whether Ollama uses the one found is known only once a model ran on it.
        other = _other_card()
        if other and other[1] >= 2048:
            card = {"HOST_GPU_NAME": other[0], "HOST_GPU_MB": str(other[1]), "HOST_GPU_KIND": "other"}
    return {**card, "HOST_RAM_MB": str(_memory_mb()), "HOST_CORES": str(_cores())}


def _other_card() -> tuple[str, int] | None:
    """The graphics card with the most memory of its own that Windows lists, as (name, MB): the registry says it in full."""
    import winreg

    best = None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}") as cards:
            for number in range(winreg.QueryInfoKey(cards)[0]):
                try:
                    with winreg.OpenKey(cards, winreg.EnumKey(cards, number)) as card:
                        name = winreg.QueryValueEx(card, "DriverDesc")[0]
                        memory = winreg.QueryValueEx(card, "HardwareInformation.qwMemorySize")[0]
                except OSError:
                    continue  # not a card, or one that does not say
                if isinstance(memory, bytes):
                    memory = int.from_bytes(memory[:8], "little")
                megabytes = round(int(memory) / 2**20)
                if best is None or megabytes > best[1]:
                    best = (str(name), megabytes)
    except OSError:
        return None
    return best


class _Memory(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in
                                                                         ("total", "free", "page_total", "page_free", "virtual_total", "virtual_free", "extended")]


def _memory_mb() -> int:
    state = _Memory()
    state.length = ctypes.sizeof(_Memory)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state))
    return round(state.total / 2**20)


def _cores() -> int:
    """The processor's cores, not its threads, as Windows counts them: one record for each."""
    kernel = ctypes.windll.kernel32
    size = ctypes.c_ulong(0)
    kernel.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))  # 0: the cores only
    records = ctypes.create_string_buffer(size.value)
    if not size.value or not kernel.GetLogicalProcessorInformationEx(0, records, ctypes.byref(size)):
        return os.cpu_count() or 0
    count, offset = 0, 0
    while offset < size.value:
        # each record begins with what it is about and how long it is
        _, length = struct.unpack_from("<II", records, offset)
        count, offset = count + 1, offset + length
    return count


# how often this PC's address in the home network is looked at again, in seconds: the router can change it at any time
FOLLOW_EVERY = 30


def follow(service, address: str, stop: threading.Event) -> None:
    """Moves the door of the phones (main.py) with this PC's address in the home network, until `stop`.
    No network for a while is not a new address: the door stays where it is until there is one."""
    while not stop.wait(FOLLOW_EVERY):
        now = home_address()
        if now and not now.startswith("127.") and now != address:
            service.move_phone_door(address, now)
            address = now


def home_address() -> str:
    """This PC's address in the network that leads out, the one a phone at home can reach; empty when there is none.
    Nothing is sent: a socket that is not really connected only asks the system which way it would go."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # an address set aside for examples: nobody has it
            return probe.getsockname()[0]
        except OSError:
            return ""


def _answers(url: str, seconds: float = 2) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=seconds) as answer:
            return answer.status == 200
    except (OSError, ValueError):
        return False


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wake_ollama() -> None:
    """Starts Ollama if it is installed for this user and does not answer, and waits a little for it."""
    if _answers(f"{OLLAMA}/api/version"):
        return
    program = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
    if not program.exists():
        return  # the page says that no model is there, and what to check
    subprocess.Popen([str(program)], creationflags=NO_WINDOW)
    for _ in range(30):
        if _answers(f"{OLLAMA}/api/version", 1):
            return
        time.sleep(1)


def say(text: str, problem: bool = False) -> None:
    """A message in a small window of Windows: what went wrong before the page could say it."""
    print(text, flush=True)
    if WINDOWED:
        ctypes.windll.user32.MessageBoxW(None, text, "Regista", 0x10 if problem else 0x40)


def _quiet(home: Path) -> None:
    """A program with no console has nowhere to write: what it says goes to regista.log, which is started over when large."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = home / "regista.log"
    if log.exists() and log.stat().st_size > 5 * 2**20:
        log.unlink()
    sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)


def music_folder() -> Path:
    """Windows' own Music folder, also when it was moved (into OneDrive, or onto another disk)."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return Path(os.path.expandvars(winreg.QueryValueEx(key, "My Music")[0]))
    except (ImportError, OSError):
        return Path.home() / "Music"


def environment(home: Path, chosen: dict, photos: Path, addresses: list[str]) -> dict:
    """What the service reads when it starts (main.py): the same names the container was given by compose.yaml."""
    phone = bool(chosen["phone"] and addresses)
    models = Path(chosen["models"]) if chosen["models"] else HERE / "models" / "phone"
    return {
        "INDEX_DIR": str(home / "index"),
        "PHOTOS_DIR": str(photos),
        "PHOTOS_LABEL": str(photos),
        "PHOTOS_READ_ONLY": "1" if chosen["read_only"] else "0",
        # the songs: the folder chosen, or Windows' own
        "MUSIC_DIR": chosen["music"] or str(music_folder()),
        "PHONE_MODELS": str(models),
        # the phone app, which a phone takes from here when it is newer than its own
        "PHONE_APP": str(HERE / "phone-app"),
        "PLACES_DIR": str(HERE / "data" / "geonames"),
        "PAGE_DIR": str(HERE / "web" / "dist"),
        "PHONE_OPEN": "1" if phone else "0",
        "PHONE_PORT": str(chosen["phone_port"]),
        "PHONE_PUBLIC_PORT": str(chosen["phone_port"]),
        # the door of the phones: on the addresses of the home network when a phone is used, else on this PC alone
        "PHONE_HOST": ",".join(addresses) if phone else "127.0.0.1",
        "HOST_ADDRESSES": ",".join(addresses) if phone else "",
        "HOST_NAME": os.environ.get("COMPUTERNAME", ""),
        **measured(),
    }


def show(url: str) -> None:
    """The page in a window of its own, until it is closed. With no way to make one (Edge's WebView2 is missing),
    the page opens in the browser, and a small window of Windows stays until the user says to stop."""
    try:
        import webview

        # a button of its own in the taskbar, with its own icon, not one shared with every Python program
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Regista")
        webview.create_window("Regista", url, width=1280, height=860, min_size=(420, 640))
        webview.start(gui="edgechromium", icon=str(ICON) if ICON.exists() else None)
    except Exception as exc:  # no WebView2 on this PC, or no way to show it
        print(f"no window of its own ({type(exc).__name__}: {exc}): the browser instead", flush=True)
        os.startfile(url)
        say("Regista è aperto nel browser. Premi OK quando vuoi chiuderlo.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="Regista", description="Regista on this PC, in a window of its own.")
    parser.add_argument("--home", help="the folder of settings.json and data (default: the program's own)")
    parser.add_argument("--photos", help="the folder of the pictures")
    parser.add_argument("--read-only", action="store_true", help="only look at the pictures")
    parser.add_argument("--phone", action="store_true", help="open the door of the phones on the home network")
    parser.add_argument("--port", type=int, help="this PC's door (8090)")
    parser.add_argument("--phone-port", type=int, help="the door of the phones (8443)")
    parser.add_argument("--no-window", action="store_true", help="serve the page and show no window, until stopped")
    options = parser.parse_args(argv)

    # as installed, the settings are next to the program; from the sources, in the user's own folder
    installed = (HERE / "settings.json").exists()
    home = Path(options.home) if options.home else HERE if installed else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Regista"
    home = home.resolve()
    (home / "index").mkdir(parents=True, exist_ok=True)
    _quiet(home)
    chosen = settings(home)
    for key, value in (("photos", options.photos), ("port", options.port), ("phone_port", options.phone_port)):
        if value:
            chosen[key] = value
    chosen["read_only"] = chosen["read_only"] or options.read_only
    chosen["phone"] = chosen["phone"] or options.phone
    url = f"http://127.0.0.1:{chosen['port']}/"

    # a Regista closed a moment ago may still hold its door for a few seconds: it is given them
    for _ in range(20):
        if _answers(f"{url}healthz"):
            # Regista is open already: one more window on it, and nothing started twice
            if not options.no_window:
                show(url)
            return 0
        if _free(int(chosen["port"])):
            break
        time.sleep(0.5)
    else:
        say(f"Un altro programma usa già la porta {chosen['port']}: chiudilo, o reinstalla Regista scegliendo un'altra porta.", problem=True)
        return 1
    photos = Path(chosen["photos"] or Path.home() / "Pictures").resolve()
    if not photos.is_dir():
        say(f"Non trovo la cartella delle foto: {photos}. Se è su un disco esterno, collegalo; "
            "oppure rilancia l'installazione e scegline un'altra.", problem=True)
        return 1
    addresses = []
    if chosen["phone"]:
        addresses = list(dict.fromkeys(address for address in [home_address(), *chosen["addresses"]] if address and not address.startswith("127.")))
        if not addresses:
            print("no network a phone could reach this PC on: the door of the phones stays on this PC alone", flush=True)

    wake_ollama()
    os.environ.update(environment(home, chosen, photos, addresses))
    # only now: the service reads its settings once, when it is loaded
    import uvicorn

    import main as service

    server = uvicorn.Server(uvicorn.Config(service.app, host="127.0.0.1", port=int(chosen["port"]), log_level="warning"))
    running = threading.Thread(target=server.run, daemon=True)
    running.start()
    for _ in range(120):
        if _answers(f"{url}healthz", 1) or not running.is_alive():
            break
        time.sleep(0.5)
    if not running.is_alive():
        say(f"Regista non è partito. Quello che è successo è scritto in {home / 'regista.log'}.", problem=True)
        return 1
    print(f"Regista: {url} (pictures: {photos}; phones: {', '.join(addresses) or 'this PC only'}, port {chosen['phone_port']})", flush=True)
    if addresses:
        threading.Thread(target=follow, args=(service, addresses[0], threading.Event()), daemon=True).start()

    if options.no_window:
        running.join()
    else:
        show(url)
        server.should_exit = True
        running.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
