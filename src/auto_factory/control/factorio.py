from __future__ import annotations

import json
import time
from typing import Any, Protocol

RESPONSE_PREFIX = "__AUTO_FACTORY__"


class RawRconClient(Protocol):
    def send_command(self, command: str) -> str | None: ...


class FactorioAPI(Protocol):
    def observe(self, radius: float) -> dict[str, Any]: ...

    def execute(self, name: str, arguments: dict[str, Any]) -> str: ...


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
        result = self._call("observe", {"radius": radius})
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
            "api_walk": "walk",
            "api_mine": "mine",
            "api_craft": "craft",
            "api_place": "place",
            "api_insert": "insert",
            "api_take": "take",
        }
        try:
            method = methods[name]
        except KeyError as exc:
            raise ValueError(f"unknown Factorio API tool: {name}") from exc

        result = self._call(method, arguments)
        if name in {"api_walk", "api_mine"}:
            duration = float(arguments["seconds"])
            try:
                time.sleep(duration)
            finally:
                self._call("stop", {})
        return json.dumps(result, separators=(",", ":"))

    def _call(self, method: str, params: dict[str, Any]) -> Any:
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
        return payload.get("result")

    @staticmethod
    def _extract_payload(response: str) -> dict[str, Any]:
        for line in reversed(response.splitlines()):
            marker = line.find(RESPONSE_PREFIX)
            if marker == -1:
                continue
            raw = line[marker + len(RESPONSE_PREFIX) :]
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Factorio returned malformed JSON") from exc
            if not isinstance(payload, dict):
                break
            return payload
        raise RuntimeError(
            "Factorio did not return an auto-factory response; is the mod enabled?"
        )
