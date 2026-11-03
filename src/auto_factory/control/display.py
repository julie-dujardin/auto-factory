from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

_FLATPAK_ROOT = Path.home() / ".var/app/com.valvesoftware.Steam"

# Factorio user-data directories (saves, mods, config), most common first.
FACTORIO_DATA_DIRS: tuple[Path, ...] = (
    Path.home() / ".factorio",  # native install (Steam, AUR, zip)
    _FLATPAK_ROOT / ".factorio",  # Flatpak Steam
)

# Factorio binaries, in search order.
FACTORIO_BINARIES: tuple[Path, ...] = (
    Path.home() / ".steam/steam/steamapps/common/Factorio/bin/x64/factorio",
    Path.home() / ".local/share/Steam/steamapps/common/Factorio/bin/x64/factorio",
    _FLATPAK_ROOT / ".local/share/Steam/steamapps/common/Factorio/bin/x64/factorio",
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


def nested_config(directory: Path) -> Path | None:
    for data_dir in FACTORIO_DATA_DIRS:
        source = data_dir / "config/config.ini"
        if not source.is_file():
            continue

        contents = source.read_text()
        contents = re.sub(
            r"(?m)^write-data=.*$",
            f"write-data={data_dir}",
            contents,
            count=1,
        )
        destination = directory / "config.ini"
        destination.write_text(contents)
        return destination
    return None


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


def main() -> None:
    argparse.ArgumentParser(
        description="Run Factorio on a private nested X display."
    ).parse_args()
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

    try:
        factorio = find_factorio()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

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
    game: subprocess.Popen | None = None
    try:
        wait_for_display(xwayland, display)
        environment = os.environ.copy()
        environment["DISPLAY"] = display
        environment["SDL_VIDEODRIVER"] = "x11"
        environment.setdefault("SteamAppId", "427520")
        environment.setdefault("SteamGameId", "427520")
        with tempfile.TemporaryDirectory(prefix="auto-factory-game-") as directory:
            config = nested_config(Path(directory))
            command = [str(factorio)]
            if config is not None:
                command.extend(["--config", str(config)])
            print(
                f"Factorio is isolated on DISPLAY={display}. In another terminal run:\n"
                "  uv run auto-factory 'your task'",
                flush=True,
            )
            game = subprocess.Popen(command, env=environment)
            raise SystemExit(game.wait())
    except KeyboardInterrupt:
        pass
    finally:
        if game is not None:
            stop(game)
        stop(xwayland)


if __name__ == "__main__":
    main()
