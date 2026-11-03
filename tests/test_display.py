from pathlib import Path

import pytest

from auto_factory.control import display


def test_find_factorio_uses_environment(tmp_path: Path, monkeypatch) -> None:
    binary = tmp_path / "factorio"
    binary.touch()
    monkeypatch.setenv("FACTORIO_BIN", str(binary))

    assert display.find_factorio() == binary


def test_nested_config_reuses_existing_data(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / ".factorio"
    config_directory = data_dir / "config"
    config_directory.mkdir(parents=True)
    (config_directory / "config.ini").write_text(
        "[path]\nread-data=__PATH__system-read-data__\n"
        "write-data=__PATH__system-write-data__\n"
    )
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    monkeypatch.setattr(display, "FACTORIO_DATA_DIRS", (data_dir,))

    result = display.nested_config(output_directory)

    assert result is not None
    assert f"write-data={data_dir}" in result.read_text()


def test_display_socket_uses_display_number() -> None:
    assert display.display_socket(":99.0") == Path("/tmp/.X11-unix/X99")


def test_macos_runs_factorio_without_xwayland(tmp_path: Path, monkeypatch) -> None:
    binary = tmp_path / "factorio"
    binary.touch()
    monkeypatch.setenv("FACTORIO_BIN", str(binary))
    monkeypatch.setattr(display, "FACTORIO_DATA_DIRS", ())
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
    assert command == [str(binary)]
    assert environment["SteamAppId"] == "427520"
