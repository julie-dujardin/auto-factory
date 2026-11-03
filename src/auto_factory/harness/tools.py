from __future__ import annotations

from typing import Any, Literal

from ..control.computer import FACTORIO_KEYS, Computer
from ..control.drag import drag_build
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
LINE_COUNT = {"type": "integer", "minimum": 1, "maximum": 50}


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
        "Read structured player, inventory, resource, and entity state around the "
        "player, including the items and fluids each entity holds, listing the 100 "
        "nearest entities. Straight transport belt runs are one entry: position is "
        "the upstream tile and the run covers length tiles toward direction. Belts "
        "give each lane's item, its count, and flow in items per second; 0 means the "
        "lane is stopped. Underground belts say whether they are the input or output "
        "end.",
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
        "api_recipe",
        "Look up how an item or fluid is made: every recipe and mineable resource "
        "producing it, with ingredients and products per craft, base crafting time, "
        "whether the recipe is unlocked (else which technology unlocks it), and for "
        "each machine that can run it (hand, furnaces, assemblers, drills) its "
        "seconds per craft, output per minute, power source, and whether you can "
        "already craft that machine. Rates ignore modules, beacons, and research "
        "bonuses.",
        _object_schema(
            {
                "item": {
                    "type": "string",
                    "description": "Exact item or fluid name, e.g. iron-gear-wheel.",
                }
            },
            ["item"],
        ),
    ),
    _tool(
        "api_entity_info",
        "Look up an entity type in general, by entity or item name: its size in "
        "tiles, power use or output, speeds, and where items and fluids go in and out. "
        "Offsets are tiles from the entity's centre, the point api_place puts at dx/dy. "
        "items says how inserters reach its inventory: any_side, fuel_any_side, or "
        "none. When facing matters, by_direction lists per facing: inserter pickup "
        "and drop tiles, a drill's item_out tile, which way a belt's items_move, fluid "
        "connections with the outside tile a pipe connects on, and size where "
        "rotation swaps it. directional false means facing changes none of these; "
        "fluids_only means it changes only the fluid connections.",
        _object_schema(
            {
                "entity": {
                    "type": "string",
                    "description": "Exact entity or item name, e.g. burner-mining-drill.",
                }
            },
            ["entity"],
        ),
    ),
    _tool(
        "api_search",
        "Find exact IDs from words or a partial or misspelled name. Returns the "
        "closest IDs per kind, best first: items, fluids, recipes, entities, "
        "entity types (for api_find's type), technologies, and entity statuses.",
        _object_schema(
            {
                "query": {
                    "type": "string",
                    "description": "Words or part of the ID, e.g. assembling machine "
                    "or gear.",
                },
                "kind": {
                    "type": "string",
                    "enum": [
                        "any",
                        "item",
                        "fluid",
                        "recipe",
                        "entity",
                        "entity_type",
                        "technology",
                        "status",
                    ],
                },
            },
            ["query", "kind"],
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
        "Place count items from inventory in a straight row starting at an offset "
        "from the player, each facing direction, stepping by the entity's size toward "
        "line_direction; a belt line uses the same value for both. Stops at the first "
        "tile that is blocked, out of build reach, or out of items, and returns how "
        "many were placed and the offset of the last one.",
        _object_schema(
            {
                "item": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "direction": DIRECTION,
                "count": LINE_COUNT,
                "line_direction": DIRECTION,
            },
            ["item", "dx", "dy", "direction", "count", "line_direction"],
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
        "Move items from a reachable entity into the player inventory, or pick up an "
        "item-on-ground. Returns the count taken per item.",
        _object_schema(
            {
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "item": {
                    "type": "string",
                    "description": "Empty takes everything the entity holds, fuel "
                    "and ingredients included.",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10000,
                    "description": "Ignored when item is empty.",
                },
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
        "api_set_recipe",
        "Set the recipe of a reachable assembling machine, chemical plant, or oil "
        "refinery; it accepts no ingredients until it has one. Furnaces pick their "
        "recipe from their input. Ingredients of a previous recipe return to the "
        "inventory.",
        _object_schema(
            {
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "recipe": {"type": "string"},
            },
            ["entity", "dx", "dy", "recipe"],
        ),
    ),
    _tool(
        "api_wait",
        "Let the game run until a condition holds or seconds of game time pass. "
        "crafts: the entity finishes count more crafts. items: the entity holds at "
        "least count of item, or the player inventory does when entity is empty. "
        "handcraft: the hand-crafting queue is empty. Returns the progress reached "
        "and the entity status, e.g. no_fuel when a machine stalls.",
        _object_schema(
            {
                "condition": {
                    "type": "string",
                    "enum": ["crafts", "items", "handcraft"],
                },
                "entity": {
                    "type": "string",
                    "description": "Entity name at dx/dy, or empty for the player.",
                },
                "dx": OFFSET,
                "dy": OFFSET,
                "item": {
                    "type": "string",
                    "description": "Item for items; else empty.",
                },
                "count": {"type": "integer", "minimum": 0, "maximum": 10000},
                "seconds": {"type": "number", "minimum": 1, "maximum": 60},
            },
            ["condition", "entity", "dx", "dy", "item", "count", "seconds"],
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


MIXED_TOOLS = [
    _tool(
        "drag_build",
        "Hold the mouse and drag a straight belt or pipe line like a player, from an "
        "offset from the player for count tiles toward direction; belts face "
        "direction. The game bridges obstacles with underground belts or pipes from "
        "your inventory. Only the part within build reach is built. Returns the items "
        "used and the offset where the drag ended.",
        _object_schema(
            {
                "item": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "direction": DIRECTION,
                "count": LINE_COUNT,
            },
            ["item", "dx", "dy", "direction", "count"],
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
# Read-only lookups that inform planning, so they run before the task has an approach.
LOOKUP_TOOL_NAMES = {
    "api_scan",
    "api_find",
    "api_recipe",
    "api_entity_info",
    "api_search",
}


def tools_for(desktop: bool, api: bool) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    if desktop:
        selected.extend(DESKTOP_TOOLS)
    if api:
        selected.extend(API_TOOLS)
    if desktop and api:
        selected.extend(MIXED_TOOLS)
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
    if name == "drag_build":
        if computer is None or factorio is None:
            raise RuntimeError("drag_build needs both computer and API control")
        return drag_build(computer, factorio, **arguments)
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
