from pathlib import Path

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
