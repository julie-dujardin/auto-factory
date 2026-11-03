from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol

RESPONSE_PREFIX = "__AUTO_FACTORY__"
# The mod caps actions at 60 game seconds; this covers slowed game speeds too.
ACTION_TIMEOUT = 120.0
POLL_INTERVAL = 0.1
# Factorio encodes an empty Lua table as {}, so array fields need restoring by name.
LIST_FIELDS: dict[str, list[tuple[str, ...]]] = {
    "observe": [("entities",), ("research", "queue"), ("research", "available")],
    "find": [("entities",)],
    "research": [("queue",), ("available",)],
}


# Factorio prints floats as long, inexact decimals (0.21 can arrive as
# 0.21000000000000002); the mod rounds to 0.01 anyway, so this only drops noise.
def _parse_float(text: str) -> float:
    return round(float(text), 2)


def _restore_empty_list(result: Any, path: tuple[str, ...]) -> None:
    parent = result
    for key in path[:-1]:
        parent = parent.get(key) if isinstance(parent, dict) else None
    if isinstance(parent, dict) and parent.get(path[-1]) == {}:
        parent[path[-1]] = []


def rcon_environment() -> tuple[str, int, str]:
    password = os.environ.get("FACTORIO_RCON_PASSWORD")
    if not password:
        raise SystemExit("Set FACTORIO_RCON_PASSWORD for API control.")
    try:
        port = int(os.environ.get("FACTORIO_RCON_PORT", "27015"))
    except ValueError as exc:
        raise SystemExit("FACTORIO_RCON_PORT must be an integer.") from exc
    return os.environ.get("FACTORIO_RCON_HOST", "127.0.0.1"), port, password


class RawRconClient(Protocol):
    def send_command(self, command: str) -> str | None: ...


class FactorioAPI(Protocol):
    def observe(self, radius: float) -> dict[str, Any]: ...

    def execute(self, name: str, arguments: dict[str, Any]) -> str: ...

    def call(self, method: str, params: dict[str, Any]) -> Any: ...


class RconFactorioAPI:
    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        client: RawRconClient | None = None,
    ) -> None:
        if client is None:
            try:
                import factorio_rcon
            except ImportError as exc:
                raise RuntimeError(
                    "RCON support is unavailable; run `uv sync`."
                ) from exc
            try:
                client = factorio_rcon.RCONClient(host, port, password)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not connect to Factorio RCON at {host}:{port}. "
                    "For graphical hosting, configure local-rcon-socket and "
                    "local-rcon-password in Factorio's config.ini, restart "
                    "Factorio, then host a multiplayer map."
                ) from exc
        self._client = client
        self._request_id = 0

    def observe(self, radius: float) -> dict[str, Any]:
        result = self.call("observe", {"radius": radius})
        if not isinstance(result, dict):
            raise RuntimeError("Factorio returned an invalid observation")
        return result

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "api_scan":
            return json.dumps(
                self.observe(float(arguments["radius"])),
                separators=(",", ":"),
            )

        methods = {
            "api_find": "find",
            "api_wait": "wait",
            "api_walk_to": "walk_to",
            "api_mine": "mine",
            "api_craft": "craft",
            "api_place": "place",
            "api_insert": "insert",
            "api_take": "take",
            "api_rotate": "rotate",
            "api_research": "research",
            "api_recipe": "recipe",
            "api_search": "search",
        }
        try:
            method = methods[name]
        except KeyError as exc:
            raise ValueError(f"unknown Factorio API tool: {name}") from exc

        result = self.call(method, arguments)
        if name in {"api_walk_to", "api_mine", "api_wait"}:
            try:
                self._wait_for_action()
            finally:
                result = self.call("stop", {})
        return json.dumps(result, separators=(",", ":"))

    def _wait_for_action(self) -> None:
        deadline = time.monotonic() + ACTION_TIMEOUT
        while time.monotonic() < deadline:
            if self.call("status", {}).get("done"):
                return
            time.sleep(POLL_INTERVAL)

    def call(self, method: str, params: dict[str, Any]) -> Any:
        self._request_id += 1
        request = {
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        command = "/af " + json.dumps(request, separators=(",", ":"))
        try:
            response = self._client.send_command(command)
        except Exception as exc:
            raise RuntimeError(f"RCON request failed: {exc}") from exc
        if response is None:
            raise RuntimeError("Factorio returned no RCON response")
        payload = self._extract_payload(response)
        if payload.get("id") != self._request_id:
            raise RuntimeError("Factorio returned a mismatched response")
        if not payload.get("ok"):
            raise ValueError(str(payload.get("error", "unknown Factorio API error")))
        result = payload.get("result")
        for path in LIST_FIELDS.get(method, []):
            _restore_empty_list(result, path)
        return result

    @staticmethod
    def _extract_payload(response: str) -> dict[str, Any]:
        for line in reversed(response.splitlines()):
            marker = line.find(RESPONSE_PREFIX)
            if marker == -1:
                continue
            raw = line[marker + len(RESPONSE_PREFIX) :]
            try:
                payload = json.loads(raw, parse_float=_parse_float)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Factorio returned malformed JSON") from exc
            if not isinstance(payload, dict):
                break
            return payload
        raise RuntimeError(
            "Factorio did not return an auto-factory response; is the mod enabled?"
        )
