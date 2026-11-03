import json
from pathlib import Path

import pytest

from auto_factory.control import display

CONFIG = """; version=13
[path]
read-data=__PATH__system-read-data__
write-data=__PATH__system-write-data__

[other]
; local-rcon-socket=0.0.0.0:0
; local-rcon-password=
"""


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    data_dir = tmp_path / "factorio"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "config/config.ini").write_text(CONFIG)
    mod_source = tmp_path / "repo/auto_factory_0.1.0"
    mod_source.mkdir(parents=True)
    monkeypatch.setattr(display, "FACTORIO_DATA_DIRS", (tmp_path / "nope", data_dir))
    monkeypatch.setattr(display, "MOD_SOURCE", mod_source)
    monkeypatch.setenv("FACTORIO_RCON_PASSWORD", r"pa\1ss")
    monkeypatch.setenv("FACTORIO_RCON_PORT", "27100")
    return data_dir


def test_find_factorio_uses_environment(tmp_path: Path, monkeypatch) -> None:
    binary = tmp_path / "factorio"
    binary.touch()
    monkeypatch.setenv("FACTORIO_BIN", str(binary))

    assert display.find_factorio() == binary


def test_prepare_game_enables_rcon(data_dir: Path, tmp_path: Path) -> None:
    config = display.prepare_game(tmp_path)

    assert config.read_text() == CONFIG.replace(
        "write-data=__PATH__system-write-data__", f"write-data={data_dir}"
    ).replace(
        "; local-rcon-socket=0.0.0.0:0", "local-rcon-socket=127.0.0.1:27100"
    ).replace("; local-rcon-password=", r"local-rcon-password=pa\1ss")


def test_set_option_adds_missing_options() -> None:
    contents = display.set_option("[other]\na=1\n", "other", "b", "2")

    assert display.set_option(contents, "path", "c", "3") == (
        "[other]\nb=2\na=1\n\n[path]\nc=3\n"
    )


def test_prepare_game_links_and_enables_mod(data_dir: Path, tmp_path: Path) -> None:
    mods = data_dir / "mods"
    mods.mkdir()
    (mods / "auto_factory_0.1.0").symlink_to(tmp_path / "old-checkout")
    (mods / "mod-list.json").write_text(
        json.dumps({"mods": [{"name": "auto_factory", "enabled": False}]})
    )

    display.prepare_game(tmp_path)

    assert (mods / "auto_factory_0.1.0").readlink() == display.MOD_SOURCE
    assert json.loads((mods / "mod-list.json").read_text()) == {
        "mods": [{"name": "auto_factory", "enabled": True}]
    }


def test_prepare_game_keeps_copied_mod(data_dir: Path, tmp_path: Path) -> None:
    (data_dir / "mods/auto_factory_0.1.0").mkdir(parents=True)

    with pytest.raises(SystemExit, match="is not a link"):
        display.prepare_game(tmp_path)


def test_prepare_game_needs_existing_config(data_dir: Path, tmp_path: Path) -> None:
    (data_dir / "config/config.ini").unlink()

    with pytest.raises(SystemExit, match="start it once"):
        display.prepare_game(tmp_path)


def test_display_socket_uses_display_number() -> None:
    assert display.display_socket(":99.0") == Path("/tmp/.X11-unix/X99")


def test_macos_runs_factorio_without_xwayland(
    data_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    binary = tmp_path / "factorio-bin"
    binary.touch()
    monkeypatch.setenv("FACTORIO_BIN", str(binary))
    monkeypatch.setattr(display.sys, "platform", "darwin")
    monkeypatch.setattr(display.sys, "argv", ["auto-factory-game"])
    launched: list[tuple[list[str], dict[str, str]]] = []

    class Game:
        def __init__(self, command: list[str], env: dict[str, str]) -> None:
            launched.append((command, env))

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(display.subprocess, "Popen", Game)

    with pytest.raises(SystemExit) as exit_info:
        display.main()

    assert exit_info.value.code == 0
    [(command, environment)] = launched
    assert command[:2] == [str(binary), "--config"]
    assert environment["SteamAppId"] == "427520"
