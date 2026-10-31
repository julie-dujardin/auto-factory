import json
import sys
from types import SimpleNamespace

import pytest

from auto_factory.control.factorio import RESPONSE_PREFIX, RconFactorioAPI


class FakeRcon:
    def __init__(self, result: object = None, error: str | None = None) -> None:
        self.result = result
        self.error = error
        self.commands: list[str] = []

    def send_command(self, command: str) -> str:
        self.commands.append(command)
        request = json.loads(command.removeprefix("/af "))
        payload = {
            "id": request["id"],
            "ok": self.error is None,
            "result": self.result,
            "error": self.error,
        }
        return "console noise\n" + RESPONSE_PREFIX + json.dumps(payload)


def test_connection_error_explains_multiplayer_requirement(monkeypatch) -> None:
    class FailedClient:
        def __init__(self, host: str, port: int, password: str) -> None:
            raise OSError("connection refused")

    monkeypatch.setitem(
        sys.modules,
        "factorio_rcon",
        SimpleNamespace(RCONClient=FailedClient),
    )

    with pytest.raises(RuntimeError, match="host a multiplayer map"):
        RconFactorioAPI("localhost", 27015, "secret")


def test_observe_sends_json_command() -> None:
    raw = FakeRcon({"tick": 10})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    assert api.observe(16) == {"tick": 10}
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert request == {"id": 1, "method": "observe", "params": {"radius": 16}}


def test_execute_returns_compact_json() -> None:
    raw = FakeRcon({"queued": 2})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    assert api.execute("api_craft", {"recipe": "iron-gear-wheel", "count": 2}) == (
        '{"queued":2}'
    )


def test_api_error_becomes_value_error() -> None:
    api = RconFactorioAPI(
        "localhost",
        27015,
        "secret",
        client=FakeRcon(error="outside reach"),
    )

    with pytest.raises(ValueError, match="outside reach"):
        api.observe(12)


def test_missing_mod_response_is_clear() -> None:
    with pytest.raises(RuntimeError, match="is the mod enabled"):
        RconFactorioAPI._extract_payload("Unknown command")


def test_empty_rcon_response_is_clear() -> None:
    class EmptyRcon:
        def send_command(self, command: str) -> None:
            return None

    api = RconFactorioAPI("localhost", 27015, "secret", client=EmptyRcon())

    with pytest.raises(RuntimeError, match="no RCON response"):
        api.observe(12)
