from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .factorio import rcon_environment

MOD_NAME = "auto_factory"
MOD_SOURCE = Path(__file__).resolve().parents[3] / "factorio_mod/auto_factory_0.1.0"

_FLATPAK_ROOT = Path.home() / ".var/app/com.valvesoftware.Steam"
_MACOS_SUPPORT = Path.home() / "Library/Application Support"
_MACOS_APP_BINARY = "factorio.app/Contents/MacOS/factorio"

# Factorio user-data directories (saves, mods, config), most common first.
FACTORIO_DATA_DIRS: tuple[Path, ...] = (
    Path.home() / ".factorio",  # native install (Steam, AUR, zip)
    _FLATPAK_ROOT / ".factorio",  # Flatpak Steam
    _MACOS_SUPPORT / "factorio",  # macOS
)

# Factorio binaries, in search order.
FACTORIO_BINARIES: tuple[Path, ...] = (
    Path.home() / ".steam/steam/steamapps/common/Factorio/bin/x64/factorio",
    Path.home() / ".local/share/Steam/steamapps/common/Factorio/bin/x64/factorio",
    _FLATPAK_ROOT / ".local/share/Steam/steamapps/common/Factorio/bin/x64/factorio",
    _MACOS_SUPPORT / "Steam/steamapps/common/Factorio" / _MACOS_APP_BINARY,
    Path("/Applications") / _MACOS_APP_BINARY,
)


def find_factorio() -> Path:
    candidates = [
        Path(os.environ["FACTORIO_BIN"]) if "FACTORIO_BIN" in os.environ else None,
        *FACTORIO_BINARIES,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise RuntimeError("Factorio was not found; set FACTORIO_BIN.")


def prepare_game(directory: Path) -> Path:
    data_dir = next(
        (path for path in FACTORIO_DATA_DIRS if (path / "config/config.ini").is_file()),
        None,
    )
    if data_dir is None:
        raise SystemExit("Factorio has no config yet; start it once, quit, and retry.")
    install_mod(data_dir / "mods")

    _, port, password = rcon_environment()
    contents = (data_dir / "config/config.ini").read_text()
    for section, key, value in (
        ("path", "write-data", str(data_dir)),
        # Loopback only: RCON runs arbitrary Lua in the game.
        ("other", "local-rcon-socket", f"127.0.0.1:{port}"),
        ("other", "local-rcon-password", password),
    ):
        contents = set_option(contents, section, key, value)
    config = directory / "config.ini"
    config.write_text(contents)
    return config


def install_mod(mods: Path) -> None:
    link = mods / MOD_SOURCE.name
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise SystemExit(
            f"{link} is not a link; remove it so this checkout's mod loads."
        )
    mods.mkdir(exist_ok=True)
    link.symlink_to(MOD_SOURCE, target_is_directory=True)

    # New mods start enabled; this only undoes an earlier disable.
    mod_list = mods / "mod-list.json"
    if not mod_list.is_file():
        return
    listing = json.loads(mod_list.read_text())
    for mod in listing["mods"]:
        if mod["name"] == MOD_NAME and not mod["enabled"]:
            mod["enabled"] = True
            mod_list.write_text(json.dumps(listing, indent=2))


def set_option(contents: str, section: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    # Factorio writes unset options as commented-out defaults.
    contents, count = re.subn(
        rf"(?m)^(?:;[ \t]*)?{re.escape(key)}=.*$", lambda _: line, contents, count=1
    )
    if count:
        return contents
    contents, count = re.subn(
        rf"(?m)^\[{section}\]$",
        lambda header: f"{header[0]}\n{line}",
        contents,
        count=1,
    )
    return contents if count else f"{contents}\n[{section}]\n{line}\n"


def wait_for_display(process: subprocess.Popen, display: str) -> None:
    socket = display_socket(display)
    deadline = time.monotonic() + 10
    while not socket.exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Xwayland exited before creating its display.")
        time.sleep(0.05)
    if not socket.exists():
        raise RuntimeError(f"Xwayland did not create DISPLAY={display}.")


def display_socket(display: str) -> Path:
    number = display.removeprefix(":").split(".", 1)[0]
    return Path("/tmp/.X11-unix") / f"X{number}"


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_game(
    factorio: Path,
    config: Path,
    environment: dict[str, str],
    banner: str,
    arguments: tuple[str, ...] = (),
) -> int:
    environment.setdefault("SteamAppId", "427520")
    environment.setdefault("SteamGameId", "427520")
    print(banner, flush=True)
    game = subprocess.Popen(
        [str(factorio), "--config", str(config), *arguments], env=environment
    )
    try:
        return game.wait()
    finally:
        stop(game)


def run_isolated(factorio: Path, config: Path) -> int:
    display = os.environ.get("AUTO_FACTORY_DISPLAY", ":99")
    size = os.environ.get("AUTO_FACTORY_SIZE", "1920x1080")
    if not re.fullmatch(r":\d+(?:\.\d+)?", display):
        raise SystemExit("AUTO_FACTORY_DISPLAY must look like :99")
    if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", size):
        raise SystemExit("AUTO_FACTORY_SIZE must look like 1920x1080")
    if shutil.which("Xwayland") is None:
        raise SystemExit("Xwayland is required for isolated computer control.")
    if display_socket(display).exists():
        raise SystemExit(f"DISPLAY={display} is already in use.")

    xwayland = subprocess.Popen(
        [
            "Xwayland",
            display,
            "-ac",
            "-nolisten",
            "tcp",
            "-geometry",
            size,
            "-decorate",
            "-noreset",
        ]
    )
    try:
        wait_for_display(xwayland, display)
        return run_game(
            factorio,
            config,
            os.environ | {"DISPLAY": display, "SDL_VIDEODRIVER": "x11"},
            f"Factorio is isolated on DISPLAY={display}. In another terminal run:\n"
            "  uv run auto-factory 'your task'",
            # The nested display has no window manager to honour fullscreen,
            # so Factorio would open a smaller window and leave black bars.
            ("--window-size", size),
        )
    finally:
        stop(xwayland)


def main() -> None:
    argparse.ArgumentParser(
        description="Run Factorio for the agent, on a private nested X display "
        "on Linux and on the main display on macOS."
    ).parse_args()
    try:
        factorio = find_factorio()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="auto-factory-game-") as directory:
        config = prepare_game(Path(directory))
        try:
            if sys.platform == "darwin":
                code = run_game(
                    factorio,
                    config,
                    os.environ.copy(),
                    "macOS has no isolated display, so the agent acts through the "
                    "API and only watches this window. Start a game, then in "
                    "another terminal run:\n"
                    "  uv run auto-factory --control mixed 'your task'",
                )
            else:
                code = run_isolated(factorio, config)
        except KeyboardInterrupt:
            return
    raise SystemExit(code)


if __name__ == "__main__":
    main()
