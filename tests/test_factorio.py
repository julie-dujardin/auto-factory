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


class ScriptedRcon:
    def __init__(self, results: dict[str, list[object]]) -> None:
        self.results = results
        self.methods: list[str] = []

    def send_command(self, command: str) -> str:
        request = json.loads(command.removeprefix("/af "))
        self.methods.append(request["method"])
        payload = {
            "id": request["id"],
            "ok": True,
            "result": self.results[request["method"]].pop(0),
        }
        return RESPONSE_PREFIX + json.dumps(payload)


def test_timed_action_polls_until_done_then_returns_stop_summary(monkeypatch) -> None:
    monkeypatch.setattr("auto_factory.control.factorio.POLL_INTERVAL", 0)
    raw = ScriptedRcon(
        {
            "walk_to": [{"done": False}],
            "status": [{"done": False}, {"done": True}],
            "stop": [{"done": True, "reason": "arrived"}],
        }
    )
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    result = api.execute("api_walk_to", {"dx": 3, "dy": -2})

    assert json.loads(result) == {"done": True, "reason": "arrived"}
    assert raw.methods == ["walk_to", "status", "status", "stop"]


def test_timed_action_stops_when_polling_fails(monkeypatch) -> None:
    raw = ScriptedRcon({"mine": [{}], "status": [], "stop": [{"done": True}]})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    with pytest.raises(RuntimeError, match="RCON request failed"):
        api.execute("api_mine", {"dx": 1, "dy": 2, "count": 5})
    assert raw.methods[-1] == "stop"


def test_belt_results_are_requested_again_for_flow(monkeypatch) -> None:
    monkeypatch.setattr("auto_factory.control.factorio.BELT_SAMPLE_SECONDS", 0)
    belt = {"name": "transport-belt", "lanes": {"left": {"item": "iron-plate"}}}
    sampled = {
        "name": "transport-belt",
        "lanes": {"left": {"item": "iron-plate", "per_second": 7.5}},
    }
    raw = ScriptedRcon(
        {
            "observe": [{"entities": [belt]}, {"entities": [sampled]}],
            "find": [{"entities": [{"name": "stone-furnace"}]}],
        }
    )
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    assert api.observe(8) == {"entities": [sampled]}
    api.execute("api_find", {"name": "furnace", "radius": 10, "limit": 5})
    assert raw.methods == ["observe", "observe", "find"]


def test_find_forwards_filters() -> None:
    raw = FakeRcon({"matched": 0, "entities": []})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)
    arguments = {
        "name": "ore",
        "type": "resource",
        "status": "",
        "radius": 200,
        "sort": "distance",
        "limit": 5,
    }

    assert api.execute("api_find", arguments) == '{"matched":0,"entities":[]}'
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert request == {"id": 1, "method": "find", "params": arguments}


def test_resources_forwards_filters_and_restores_patches() -> None:
    raw = FakeRcon({"patches": {}, "omitted": 0})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)
    arguments = {"name": "water", "limit": 5}

    result = api.execute("api_resources", arguments)

    assert json.loads(result) == {"patches": [], "omitted": 0}
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert request == {"id": 1, "method": "resources", "params": arguments}


def test_wait_polls_until_done_then_stops() -> None:
    raw = FakeRcon({"done": True, "reason": "condition met"})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)
    arguments = {
        "condition": "crafts",
        "entity": "stone-furnace",
        "dx": 2,
        "dy": 0,
        "item": "",
        "count": 5,
        "seconds": 30,
    }

    api.execute("api_wait", arguments)
    methods = [
        json.loads(command.removeprefix("/af "))["method"] for command in raw.commands
    ]
    assert methods == ["wait", "status", "stop"]


def test_empty_lua_arrays_become_lists() -> None:
    raw = FakeRcon(
        {
            "entities": {},
            "resources": {},
            "research": {"queue": {}, "available": 0, "triggers": 0},
        }
    )
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    assert api.observe(8) == {
        "entities": [],
        "resources": {},
        "research": {"queue": [], "available": 0, "triggers": 0},
    }


def test_float_noise_is_rounded_away() -> None:
    payload = RconFactorioAPI._extract_payload(
        RESPONSE_PREFIX + '{"ok":true,"result":{"dx":-0.8800000000000000710542735760}}'
    )

    assert payload["result"] == {"dx": -0.88}


def test_recipe_forwards_item() -> None:
    raw = FakeRcon({"item": "iron-plate", "recipes": {}, "mining": {}})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    api.execute("api_recipe", {"item": "iron-plate", "include_locked": True})
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert request == {
        "id": 1,
        "method": "recipe",
        "params": {"item": "iron-plate", "include_locked": True},
    }


def test_entity_info_forwards_entity() -> None:
    raw = FakeRcon({"entity": "inserter", "directional": True})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    api.execute("api_entity_info", {"entity": "inserter"})
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert request == {
        "id": 1,
        "method": "entity_info",
        "params": {"entity": "inserter"},
    }


def test_search_forwards_query() -> None:
    raw = FakeRcon({"item": ["iron-gear-wheel"]})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    assert api.execute("api_search", {"query": "gear", "kind": "item"}) == (
        '{"item":["iron-gear-wheel"]}'
    )
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert request["method"] == "search"


def test_technology_restores_empty_lists() -> None:
    raw = FakeRcon(
        {
            "technology": "automation",
            "unlocks_recipes": {},
            "effects": {},
            "prerequisites": {},
            "missing_prerequisites": {},
            "successors": {},
        }
    )
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)

    result = json.loads(api.execute("api_technology", {"technology": "automation"}))
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert (request["method"], request["params"]) == (
        "technology",
        {"technology": "automation"},
    )
    assert result == {
        "technology": "automation",
        "unlocks_recipes": [],
        "effects": [],
        "prerequisites": [],
        "missing_prerequisites": [],
        "successors": [],
    }


def test_technologies_restores_an_empty_list() -> None:
    raw = FakeRcon({"matched": 0, "technologies": {}})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)
    arguments = {
        "query": "",
        "status": "available",
        "completes_by": "labs",
        "packs": ["automation-science-pack"],
        "unlocks": "",
        "limit": 10,
    }

    result = json.loads(api.execute("api_technologies", arguments))
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert (request["method"], request["params"]) == ("technologies", arguments)
    assert result == {"matched": 0, "technologies": []}


def test_set_recipe_forwards_target() -> None:
    raw = FakeRcon({"entity": "assembling-machine-2", "recipe": "iron-gear-wheel"})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)
    arguments = {
        "entity": "assembling-machine-2",
        "dx": 2.5,
        "dy": 5,
        "recipe": "iron-gear-wheel",
    }

    api.execute("api_set_recipe", arguments)
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert (request["method"], request["params"]) == ("set_recipe", arguments)


def test_connect_forwards_targets() -> None:
    raw = FakeRcon({"placed": "inserter", "count": 1})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)
    arguments = {
        "item": "inserter",
        "pickup_from": 12,
        "drop_into": 34,
        "power": [],
        "count": 1,
    }

    api.execute("api_connect", arguments)
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert (request["method"], request["params"]) == ("connect", arguments)


def test_underground_forwards_pair() -> None:
    raw = FakeRcon({"placed": "underground-belt", "under": 3})
    api = RconFactorioAPI("localhost", 27015, "secret", client=raw)
    arguments = {
        "item": "underground-belt",
        "anchor": 7,
        "anchor_point": "ahead",
        "point": "centre",
        "dx": 0,
        "dy": 0,
        "direction": "east",
        "under": 3,
    }

    api.execute("api_underground", arguments)
    request = json.loads(raw.commands[0].removeprefix("/af "))
    assert (request["method"], request["params"]) == ("underground", arguments)
