import json
import shlex
from typing import ClassVar

import pytest

from auto_factory.harness import tool_cli


class RecordingFactorio:
    calls: ClassVar[list[tuple[str, dict[str, object]]]] = []

    def __init__(self, host: str, port: int, password: str) -> None:
        pass

    def execute(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, arguments))
        return '{"ok":true}'


@pytest.fixture
def factorio(monkeypatch) -> type[RecordingFactorio]:
    monkeypatch.setenv("FACTORIO_RCON_PASSWORD", "secret")
    monkeypatch.setattr(RecordingFactorio, "calls", [])
    monkeypatch.setattr(tool_cli, "RconFactorioAPI", RecordingFactorio)
    return RecordingFactorio


def run(monkeypatch, command: str) -> None:
    monkeypatch.setattr(
        tool_cli.sys, "argv", ["auto-factory-tool", *shlex.split(command)]
    )
    tool_cli.main()


def test_flags_fill_empty_strings(monkeypatch, capsys, factorio) -> None:
    run(monkeypatch, "find --name ore --radius 50 --sort distance --limit 3")

    assert factorio.calls == [
        (
            "api_find",
            {
                "name": "ore",
                "type": "",
                "status": "",
                "radius": 50.0,
                "sort": "distance",
                "limit": 3,
            },
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_flags_override_pasted_arguments(monkeypatch, factorio) -> None:
    run(monkeypatch, """api_walk_to '{"dx": 1, "dy": 2}' --dy -3""")

    assert factorio.calls == [("api_walk_to", {"dx": 1, "dy": -3.0})]


def test_booleans_default_false(monkeypatch, factorio) -> None:
    run(monkeypatch, "rotate --entity inserter --dx 1 --dy 0")

    assert factorio.calls[0][1]["reverse"] is False


def test_schema_defaults_fill_omitted_fields(monkeypatch, factorio) -> None:
    run(
        monkeypatch,
        "place --item iron-chest --dx 1 --dy 0 --direction north --count 1 "
        "--line-direction north",
    )

    arguments = factorio.calls[0][1]
    assert (
        arguments | {"anchor": 0, "anchor_point": "centre", "point": "centre", "gap": 0}
        == arguments
    )


def test_array_flags_take_several_values(monkeypatch, factorio) -> None:
    run(monkeypatch, "connect --item medium-electric-pole --power 12 34 --count 1")

    assert factorio.calls == [
        (
            "api_connect",
            {
                "item": "medium-electric-pole",
                "pickup_from": 0,
                "drop_into": 0,
                "power": [12, 34],
                "count": 1,
            },
        )
    ]


def test_missing_required_argument_exits(monkeypatch, capsys, factorio) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, "craft --recipe iron-gear-wheel")

    assert exit_info.value.code == 2
    assert "api_craft needs --count" in capsys.readouterr().err
    assert factorio.calls == []


def test_game_error_exits_nonzero(monkeypatch, capsys, factorio) -> None:
    def refuse(self, name: str, arguments: dict[str, object]) -> str:
        raise ValueError("target is out of reach")

    monkeypatch.setattr(RecordingFactorio, "execute", refuse)

    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, "scan --radius 12")

    assert exit_info.value.code == 1
    assert "target is out of reach" in capsys.readouterr().err
