from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from ..control.factorio import RconFactorioAPI, rcon_environment
from .tools import API_TOOLS

TOOLS = {tool["function"]["name"]: tool["function"] for tool in API_TOOLS}
ARGUMENT_TYPES = {"number": float, "integer": int, "string": str}


# Omitted fields take the schema's default; omitted free-text strings mean "any" or
# "the player", as the schemas describe.
def empty_value(schema: dict[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    if schema["type"] == "boolean":
        return False
    if schema["type"] == "string" and "enum" not in schema:
        return ""
    return None


def json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("arguments must be a JSON object")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Call one Factorio API tool the way the agent does.",
    )
    commands = result.add_subparsers(required=True, metavar="TOOL")
    for name, function in TOOLS.items():
        command = commands.add_parser(
            name.removeprefix("api_"),
            aliases=[name],
            help=re.split(r"\.\s+(?=[A-Z])", function["description"])[0].removesuffix(
                "."
            ),
            description=function["description"],
        )
        command.set_defaults(tool=name)
        command.add_argument(
            "arguments",
            nargs="?",
            type=json_object,
            default={},
            help="JSON object of arguments, e.g. copied from a trace; flags override it",
        )
        required = function["parameters"]["required"]
        for field, schema in function["parameters"]["properties"].items():
            flag = "--" + field.replace("_", "-")
            help_text = schema.get("description", "")
            if field in required and empty_value(schema) is None:
                help_text = f"{help_text} (required)".strip()
            if schema["type"] == "boolean":
                command.add_argument(
                    flag, action="store_true", default=argparse.SUPPRESS, help=help_text
                )
            elif schema["type"] == "array":
                command.add_argument(
                    flag,
                    type=ARGUMENT_TYPES[schema["items"]["type"]],
                    nargs="*",
                    default=argparse.SUPPRESS,
                    help=help_text,
                )
            else:
                command.add_argument(
                    flag,
                    type=ARGUMENT_TYPES[schema["type"]],
                    choices=schema.get("enum"),
                    default=argparse.SUPPRESS,
                    help=help_text,
                )
    return result


def main() -> None:
    command_line = parser()
    args = vars(command_line.parse_args())
    name = args.pop("tool")
    parameters = TOOLS[name]["parameters"]
    defaults = {
        field: value
        for field, schema in parameters["properties"].items()
        if (value := empty_value(schema)) is not None
    }
    arguments = defaults | args.pop("arguments") | args
    if missing := [field for field in parameters["required"] if field not in arguments]:
        flags = ", ".join("--" + field.replace("_", "-") for field in missing)
        command_line.error(f"{name} needs {flags}")

    try:
        factorio = RconFactorioAPI(*rcon_environment())
        result = factorio.execute(name, arguments)
    except (RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        raise SystemExit(130) from None
    print(json.dumps(json.loads(result), indent=2))
