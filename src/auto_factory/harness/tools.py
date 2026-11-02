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


OFFSET = {
    "type": "number",
    "minimum": -100,
    "maximum": 100,
    "description": "Tiles from the player; positive dx is east, positive dy is south.",
}
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
        "api_find",
        "Search entities around the player over a wider area than api_scan, e.g. the "
        "nearest iron-ore or every furnace with no_fuel. Returns per-name totals for all "
        "matches and the first limit entities after sorting. Needs a name or type.",
        _object_schema(
            {
                "name": {
                    "type": "string",
                    "description": "Substring of the entity name, e.g. ore or "
                    "burner-mining-drill. Empty matches any name.",
                },
                "type": {
                    "type": "string",
                    "description": "Exact entity type, e.g. resource, tree, furnace, "
                    "mining-drill, container. Empty matches any type.",
                },
                "status": {
                    "type": "string",
                    "description": "Exact entity status, e.g. working, no_fuel, "
                    "no_input_fluid, waiting_for_source_items. Empty matches any.",
                },
                "radius": {"type": "number", "minimum": 1, "maximum": 256},
                "sort": {
                    "type": "string",
                    "enum": ["distance", "amount", "name"],
                    "description": "amount is resource amount or total item count, "
                    "largest first.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["name", "type", "status", "radius", "sort", "limit"],
        ),
    ),
    _tool(
        "api_walk_to",
        "Walk by an offset in tiles using normal character movement and collision. "
        "Returns whether the player arrived or got blocked, how far it moved, and the "
        "offset still remaining to the target.",
        _object_schema(
            {
                "dx": OFFSET,
                "dy": OFFSET,
            },
            ["dx", "dy"],
        ),
    ),
    _tool(
        "api_mine",
        "Mine the entity or resource at an offset from the player using normal reach "
        "and mining speed, until count items were gained or the target is gone.",
        _object_schema(
            {
                "dx": OFFSET,
                "dy": OFFSET,
                "count": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ["dx", "dy", "count"],
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
        "Place one item from inventory at an offset from the player within normal "
        "build reach.",
        _object_schema(
            {
                "item": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "direction": DIRECTION,
            },
            ["item", "dx", "dy", "direction"],
        ),
    ),
    _tool(
        "api_insert",
        "Move items from the player inventory into a reachable entity.",
        _object_schema(
            {
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "item": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
            ["entity", "dx", "dy", "item", "count"],
        ),
    ),
    _tool(
        "api_take",
        "Move items from a reachable entity into the player inventory.",
        _object_schema(
            {
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "item": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
            ["entity", "dx", "dy", "item", "count"],
        ),
    ),
    _tool(
        "api_rotate",
        "Rotate a reachable placed entity clockwise, or counterclockwise when reverse.",
        _object_schema(
            {
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "reverse": {"type": "boolean"},
            },
            ["entity", "dx", "dy", "reverse"],
        ),
    ),
    _tool(
        "api_research",
        "Queue a lab technology for research. The scan lists which are available.",
        _object_schema(
            {"technology": {"type": "string"}},
            ["technology"],
        ),
    ),
]


TASK_TEXT = {"type": "string", "maxLength": 500}

TASK_TOOLS = [
    _tool(
        "add_tasks",
        "Split the current task into ordered subtasks. The first one becomes current.",
        _object_schema(
            {
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": _object_schema(
                        {
                            "title": {"type": "string", "maxLength": 200},
                            "done_when": {
                                "type": "string",
                                "maxLength": 300,
                                "description": "A condition you can check in the "
                                "observations.",
                            },
                        },
                        ["title", "done_when"],
                    ),
                }
            },
            ["tasks"],
        ),
    ),
    _tool(
        "propose_approaches",
        "Give the current task 2-4 genuinely different ways to do it, best first. The "
        "first is tried; the rest are fallbacks taken in order by fail_task.",
        _object_schema(
            {
                "approaches": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 4,
                    "items": {"type": "string", "maxLength": 300},
                },
                "reason": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Why the first approach fits the goal best.",
                },
            },
            ["approaches", "reason"],
        ),
    ),
    _tool(
        "complete_task",
        "Close the current task once its done_when holds. Its steps leave your context.",
        _object_schema(
            {
                "result": TASK_TEXT
                | {
                    "description": "What was achieved, with the locations and facts "
                    "later tasks need."
                }
            },
            ["result"],
        ),
    ),
    _tool(
        "fail_task",
        "Abandon the current approach. The next approach takes over, or the parent "
        "task replans. Its steps leave your context.",
        _object_schema(
            {
                "reason": TASK_TEXT
                | {"description": "Why it failed and what was learned."}
            },
            ["reason"],
        ),
    ),
]
TASK_TOOL_NAMES = {tool["function"]["name"] for tool in TASK_TOOLS}


def tools_for_mode(mode: ControlMode) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    if mode in {"computer", "mixed"}:
        selected.extend(DESKTOP_TOOLS)
    if mode in {"api", "mixed"}:
        selected.extend(API_TOOLS)
    selected.extend(TASK_TOOLS)
    return selected


def execute_tool(
    computer: Computer | None,
    factorio: FactorioAPI | None,
    name: str,
    arguments: dict[str, Any],
) -> str:
    if name in TASK_TOOL_NAMES:
        raise ValueError(f"{name} is handled by the agent loop")
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
