from __future__ import annotations

from typing import Any, Literal

from ..control.computer import FACTORIO_KEYS, Computer
from ..control.factorio import FactorioAPI

ControlMode = Literal["computer", "api", "mixed"]


def _object_schema(
    properties: dict[str, dict[str, Any]],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


COORDINATE = {"type": "number", "description": "Absolute Factorio world coordinate."}
DIRECTION = {"type": "string", "enum": ["north", "east", "south", "west"]}


DESKTOP_TOOLS = [
    _tool(
        "game_action",
        "Press a Factorio control by its meaning. Movement and shooting may be held.",
        _object_schema(
            {
                "action": {
                    "type": "string",
                    "enum": list(FACTORIO_KEYS),
                    "description": "The semantic Factorio action.",
                },
                "duration": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "Seconds to hold the control. Use about 0.1 for a tap.",
                },
            },
            ["action", "duration"],
        ),
    ),
    _tool(
        "type_text",
        "Type text into the currently focused Factorio field.",
        _object_schema(
            {
                "text": {"type": "string", "maxLength": 500},
                "interval": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 2,
                    "description": "Delay after typing, in seconds.",
                },
            },
            ["text", "interval"],
        ),
    ),
    _tool(
        "move_cursor",
        "Move the pointer. Coordinates are normalized to [0, 1000] within the screenshot.",
        _object_schema(
            {
                "x": {"type": "integer", "minimum": 0, "maximum": 1000},
                "y": {"type": "integer", "minimum": 0, "maximum": 1000},
                "duration": {"type": "number", "minimum": 0, "maximum": 5},
            },
            ["x", "y", "duration"],
        ),
    ),
    _tool(
        "click",
        "Click or hold at normalized screenshot coordinates. In the world, left click "
        "builds/selects and holding right click mines.",
        _object_schema(
            {
                "x": {"type": "integer", "minimum": 0, "maximum": 1000},
                "y": {"type": "integer", "minimum": 0, "maximum": 1000},
                "button": {"type": "string", "enum": ["left", "middle", "right"]},
                "clicks": {"type": "integer", "minimum": 1, "maximum": 3},
                "hold_seconds": {"type": "number", "minimum": 0, "maximum": 10},
            },
            ["x", "y", "button", "clicks", "hold_seconds"],
        ),
    ),
    _tool(
        "drag",
        "Drag between normalized screenshot coordinates, useful for GUI slots and map movement.",
        _object_schema(
            {
                "start_x": {"type": "integer", "minimum": 0, "maximum": 1000},
                "start_y": {"type": "integer", "minimum": 0, "maximum": 1000},
                "end_x": {"type": "integer", "minimum": 0, "maximum": 1000},
                "end_y": {"type": "integer", "minimum": 0, "maximum": 1000},
                "button": {"type": "string", "enum": ["left", "middle", "right"]},
                "duration": {"type": "number", "minimum": 0, "maximum": 5},
            },
            ["start_x", "start_y", "end_x", "end_y", "button", "duration"],
        ),
    ),
    _tool(
        "scroll",
        "Scroll at normalized coordinates. Positive scrolls up/zooms in; negative "
        "scrolls down/zooms out.",
        _object_schema(
            {
                "x": {"type": "integer", "minimum": 0, "maximum": 1000},
                "y": {"type": "integer", "minimum": 0, "maximum": 1000},
                "amount": {"type": "integer", "minimum": -20, "maximum": 20},
            },
            ["x", "y", "amount"],
        ),
    ),
    _tool(
        "wait",
        "Wait for the game, an animation, or a previous action to settle.",
        _object_schema(
            {"seconds": {"type": "number", "minimum": 0, "maximum": 30}},
            ["seconds"],
        ),
    ),
]


API_TOOLS = [
    _tool(
        "api_scan",
        "Read structured player, inventory, resource, and entity state around the player.",
        _object_schema(
            {"radius": {"type": "number", "minimum": 2, "maximum": 64}},
            ["radius"],
        ),
    ),
    _tool(
        "api_walk",
        "Walk using normal character movement and collision.",
        _object_schema(
            {
                "direction": DIRECTION,
                "seconds": {"type": "number", "minimum": 0.1, "maximum": 10},
            },
            ["direction", "seconds"],
        ),
    ),
    _tool(
        "api_mine",
        "Mine the entity or resource at an absolute world position using normal reach "
        "and mining speed.",
        _object_schema(
            {
                "x": COORDINATE,
                "y": COORDINATE,
                "seconds": {"type": "number", "minimum": 0.1, "maximum": 10},
            },
            ["x", "y", "seconds"],
        ),
    ),
    _tool(
        "api_craft",
        "Queue a hand-crafting recipe, consuming ingredients and taking normal crafting time.",
        _object_schema(
            {
                "recipe": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["recipe", "count"],
        ),
    ),
    _tool(
        "api_place",
        "Place one item from inventory at an absolute world position within normal build reach.",
        _object_schema(
            {
                "item": {"type": "string"},
                "x": COORDINATE,
                "y": COORDINATE,
                "direction": DIRECTION,
            },
            ["item", "x", "y", "direction"],
        ),
    ),
    _tool(
        "api_insert",
        "Move items from the player inventory into a reachable entity.",
        _object_schema(
            {
                "entity": {"type": "string"},
                "x": COORDINATE,
                "y": COORDINATE,
                "item": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
            ["entity", "x", "y", "item", "count"],
        ),
    ),
    _tool(
        "api_take",
        "Move items from a reachable entity into the player inventory.",
        _object_schema(
            {
                "entity": {"type": "string"},
                "x": COORDINATE,
                "y": COORDINATE,
                "item": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
            ["entity", "x", "y", "item", "count"],
        ),
    ),
]


ANSWER_TOOL = _tool(
    "answer",
    "Finish the task and report the result.",
    _object_schema(
        {"content": {"type": "string", "description": "A concise completion report."}},
        ["content"],
    ),
)


def tools_for_mode(mode: ControlMode) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    if mode in {"computer", "mixed"}:
        selected.extend(DESKTOP_TOOLS)
    if mode in {"api", "mixed"}:
        selected.extend(API_TOOLS)
    selected.append(ANSWER_TOOL)
    return selected


def execute_tool(
    computer: Computer | None,
    factorio: FactorioAPI | None,
    name: str,
    arguments: dict[str, Any],
) -> str:
    if name == "answer":
        raise ValueError("answer is handled by the agent loop")
    if name.startswith("api_"):
        if factorio is None:
            raise RuntimeError("Factorio API control is not configured")
        return factorio.execute(name, arguments)
    if computer is None:
        raise RuntimeError("computer control is not configured")
    handlers = {
        "game_action": computer.game_action,
        "type_text": computer.type_text,
        "move_cursor": computer.move_cursor,
        "click": computer.click,
        "drag": computer.drag,
        "scroll": computer.scroll,
        "wait": computer.wait,
    }
    try:
        handler = handlers[name]
    except KeyError as exc:
        raise ValueError(f"unknown tool: {name}") from exc
    handler(**arguments)
    return "ok"
