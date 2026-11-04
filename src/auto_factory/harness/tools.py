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
    "description": "Tiles from the centre of the tile the player started the run "
    "on; positive dx is east, positive dy is south.",
}
DIRECTION = {"type": "string", "enum": ["north", "east", "south", "west"]}
FACING = {
    "type": "string",
    "enum": ["north", "east", "south", "west", "any"],
    "description": "any for an entity whose facing moves no items: api_entity_info "
    "directional false or fluids_only. It then faces north.",
}
LINE_COUNT = {"type": "integer", "minimum": 1, "maximum": 50}
ENTITY_ID = {
    "type": "integer",
    "minimum": 0,
    "default": 0,
    "description": "An entity id from api_scan, api_find, api_place, or api_connect.",
}
TARGET_ID = ENTITY_ID | {
    "description": "The entity's id; 0 finds it by entity name at dx/dy instead."
}


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
                "text": {"type": "string"},
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
        "nearest entities, cliffs included; omitted counts those beyond the cut. "
        "The player gives position: the tile it stands on; build_distance: how far "
        "from it an entity's centre can be "
        "built; reach_distance: how far an entity can be to insert into, take from, "
        "rotate, set the recipe of, or mine it; and resource_reach_distance: how far "
        "a resource tile can be to mine it. "
        "Machines split their items into input_slots, output_slots, fuel, "
        "burnt_result, modules, and trash; other inventories, such as chests and the "
        "stack of an item-on-ground, are items. Their fluids are input_fluids and "
        "output_fluids; pipes and tanks hold fluids. Crafting machines give fed_by "
        "and emptied_by: the inserters and drills dropping into them and the "
        "inserters taking from them, with a warning when nothing takes their "
        "products out. Entities whose facing moves only pipe connections give "
        "pipes_face instead of direction. Inserters give held: the stack in "
        "their hand, and takes_from: where they pick up; inserters and mining drills "
        "give gives_to: where they drop. Both give tile: the tile reached, and name "
        "nothing or ground when no entity holds items there, else "
        "that entity's id and name, plus for a belt the lanes of that one tile under "
        "the tile's own id, for a crafting machine its recipe, and for anything else "
        "the items it holds. Entities give an id that stays fixed as the player moves. "
        "Straight transport belt runs are one entry: from and to are its upstream and "
        "downstream end tiles, giving the coordinate along direction as beyond scan "
        "where the run carries on past radius; id is its upstream-most scanned "
        "tile's. beyond_scan lists upstream when other belts "
        "outside radius feed the run, and downstream when it feeds one there. Belts "
        "give each lane's item, its count, and flow in items per second; 0 means the "
        "lane is stopped. Underground belts say whether they are the input or output "
        "end. Underground belts and pipes give pair: the other end's position, or "
        "unconnected. Electric poles give supply_area: the left_top and right_bottom "
        "corners of the square they cover, powering every machine that overlaps it; and "
        "network: the id of the electric network they are wired into. power_networks "
        "lists each network of the listed poles once with available_kw that its "
        "generators can supply and demand_kw that its machines draw; poles with "
        "different ids share no power. Mining drills give mining_area: the corners of "
        "the area they mine, and mines: the amount left in it per resource they can "
        "mine, or yield_percent for infinite ones such as crude oil. Inserters set to "
        "filter give filter_mode: whitelist moves only the items in filters, blacklist "
        "all others; and stack_size_override when set. Splitters give input_priority "
        "and output_priority: left, right, or none, seen facing their direction; and "
        "filter: the item sent out the output_priority side and the rest out the other. "
        "research gives the current technology and its progress fraction, the queue, "
        "last_researched, available: each lab technology whose prerequisites are "
        "researched with its cost of units, science packs per unit, and seconds per "
        "unit, and progress when partly researched; triggers: technologies that "
        "complete on an action instead, with what it needs; and bonuses: research "
        "bonuses in effect.",
        _object_schema(
            {"radius": {"type": "number", "minimum": 2, "maximum": 64}},
            ["radius"],
        ),
    ),
    _tool(
        "api_find",
        "Search entities around the player over a wider area than api_scan, e.g. the "
        "nearest iron-ore or every furnace with no_fuel. Returns per-name totals for all "
        "matches and the first limit entities after sorting, read as in api_scan, "
        "power_networks included. Needs a name or type.",
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
        "api_resources",
        "Find resource patches anywhere on the charted map, nearest first: ores, "
        "crude oil, and water named by the fluid offshore pumps draw from it. Tiles "
        "of one resource lying close together form a patch, as on the map; partial "
        "means it reaches uncharted land, so it may continue and its totals may be "
        "lower bounds. Each patch gives distance from the player and "
        "nearest: the position of its closest tile. Ores give amount, tiles, and area: "
        "the left_top and right_bottom corners of the patch; infinite resources such "
        "as crude oil give yield_percent summed over their wells instead of amount. "
        "Water gives coastline: its count of shore tiles.",
        _object_schema(
            {
                "name": {
                    "type": "string",
                    "description": "Substring of the resource name, e.g. iron-ore, "
                    "ore, crude-oil, or water. Empty matches all.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["name", "limit"],
        ),
    ),
    _tool(
        "api_walk_to",
        "Walk to a position using normal character movement and collision. Returns "
        "whether the player arrived or got blocked, the position of the tile it "
        "stands on, and the target.",
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
        "Mine the entity or resource at a position using normal reach "
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
        "Look up how an item or fluid is made: every unlocked recipe and mineable "
        "resource producing it, with ingredients and products per craft, base "
        "crafting time, and for each machine that can run it (hand, furnaces, "
        "assemblers, drills) its seconds per craft, output per minute, power "
        "source, and whether you can already craft that machine. locked lists "
        "recipes not yet researched with the technologies that unlock them; "
        "include_locked gives them in full, marked unlocked false with unlocked_by. "
        "Rates ignore modules, beacons, and research bonuses; api_scan lists the "
        "bonuses.",
        _object_schema(
            {
                "item": {
                    "type": "string",
                    "description": "Exact item or fluid name, e.g. iron-gear-wheel.",
                },
                "include_locked": {"type": "boolean"},
            },
            ["item", "include_locked"],
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
        "api_technology",
        "Look up a technology: status (researched, researching, queued, available, "
        "locked, or disabled), cost or trigger, progress, the recipes it unlocks and "
        "its other effects, its direct prerequisites, missing_prerequisites: every "
        "unresearched technology it needs, each after its own prerequisites; and "
        "successors: the technologies it leads to.",
        _object_schema(
            {
                "technology": {
                    "type": "string",
                    "description": "Exact technology name, e.g. automation-2.",
                }
            },
            ["technology"],
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
        "Place count items from inventory in a straight row, each facing direction, "
        "stepping by the entity's size toward line_direction; a belt line uses the "
        "same value for both. at says where the first goes relative to the anchor: "
        "offset centres it dx/dy from the anchor's centre, snapped to the grid; a "
        "side puts it flush against that side of the anchor, along tiles from the "
        "side's north or west end; item_out covers a mining drill's output tile, "
        "pickup and drop an inserter's, ahead the tile past the downstream end of a "
        "transport belt's straight run, and behind the tile before its upstream end. "
        "When the player stands in the way they step aside, and stepped_aside gives "
        "the tile they moved to. Stops at the first tile that "
        "is blocked, out of build reach, or out of items. Returns how many were "
        "placed, the positions of the first and last, snapped_from when snapping moved "
        "the first, direction: any when facing changes nothing, or pipes_face "
        "instead when it moves only pipe connections, and built: each entity's id, "
        "takes_from and gives_to as in "
        "api_scan, and what it is fed or emptied by, powers, or joins by pipe "
        "(fluid_to), with warnings for "
        "ends that lead nowhere; a belt or pipe line lists only its two ends.",
        _object_schema(
            {
                "item": {"type": "string"},
                "anchor": ENTITY_ID
                | {
                    "description": "Id of the entity to place relative to; 0 is the "
                    "run's start tile, which only takes offset."
                },
                "at": {
                    "type": "string",
                    "enum": [
                        "offset",
                        "north",
                        "east",
                        "south",
                        "west",
                        "item_out",
                        "pickup",
                        "drop",
                        "ahead",
                        "behind",
                    ],
                    "default": "offset",
                },
                "along": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 20,
                    "default": 0,
                    "description": "For a side: tiles from the side's north or west "
                    "end to the entity's north or west edge.",
                },
                "dx": OFFSET | {"description": "For offset: tiles east of the anchor."},
                "dy": OFFSET
                | {"description": "For offset: tiles south of the anchor."},
                "direction": FACING,
                "count": LINE_COUNT,
                "line_direction": DIRECTION,
            },
            [
                "item",
                "anchor",
                "at",
                "along",
                "dx",
                "dy",
                "direction",
                "count",
                "line_direction",
            ],
        ),
    ),
    _tool(
        "api_connect",
        "Place an inserter or electric pole where it connects existing entities, "
        "choosing its position and facing. An inserter takes from pickup_from and "
        "drops into drop_into, where a transport belt stands for its whole straight "
        "run; count inserters go side by side, nearest the middle of the two first. "
        "An electric pole covers every entity in power with its supply area, in wire "
        "reach of an existing pole when it can. Tries each fitting spot until one is "
        "free and in build reach. Returns built and stepped_aside as api_place does.",
        _object_schema(
            {
                "item": {"type": "string"},
                "pickup_from": ENTITY_ID
                | {"description": "Entity id for an inserter to take from; else 0."},
                "drop_into": ENTITY_ID
                | {"description": "Entity id for an inserter to drop into; else 0."},
                "power": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": 20,
                    "default": [],
                    "description": "Entity ids for an electric pole to power; else "
                    "empty.",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Inserters to place; a pole is always one.",
                },
            },
            ["item", "pickup_from", "drop_into", "power", "count"],
        ),
    ),
    _tool(
        "api_insert",
        "Move items from the player inventory into a reachable entity.",
        _object_schema(
            {
                "id": TARGET_ID,
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "item": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
            ["id", "entity", "dx", "dy", "item", "count"],
        ),
    ),
    _tool(
        "api_take",
        "Move items from a reachable entity into the player inventory, or pick up an "
        "item-on-ground. Returns the count taken per item.",
        _object_schema(
            {
                "id": TARGET_ID,
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
            ["id", "entity", "dx", "dy", "item", "count"],
        ),
    ),
    _tool(
        "api_rotate",
        "Rotate a reachable placed entity clockwise, or counterclockwise when reverse. "
        "Returns its new direction, or pipes_face when facing moves only pipe "
        "connections.",
        _object_schema(
            {
                "id": TARGET_ID,
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "reverse": {"type": "boolean"},
            },
            ["id", "entity", "dx", "dy", "reverse"],
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
                "id": TARGET_ID,
                "entity": {"type": "string"},
                "dx": OFFSET,
                "dy": OFFSET,
                "recipe": {"type": "string"},
            },
            ["id", "entity", "dx", "dy", "recipe"],
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
                "id": TARGET_ID,
                "entity": {
                    "type": "string",
                    "description": "Entity name at dx/dy, or empty with id 0 for the "
                    "player.",
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
            ["condition", "id", "entity", "dx", "dy", "item", "count", "seconds"],
        ),
    ),
    _tool(
        "api_research",
        "Queue a lab technology for research. The scan lists which are available; "
        "api_technology says what a locked one needs first.",
        _object_schema(
            {"technology": {"type": "string"}},
            ["technology"],
        ),
    ),
]


MIXED_TOOLS = [
    _tool(
        "drag_build",
        "Hold the mouse and drag a straight belt or pipe line like a player, from a "
        "position for count tiles toward direction; belts face "
        "direction. The game bridges obstacles with underground belts or pipes from "
        "your inventory. Only the part within build reach is built. Returns the items "
        "used and the position where the drag ended.",
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


# The model server enforces maxLength by cutting text mid-word, sometimes then padding
# whitespace up to the output limit, so text fields only ask for brevity.
TASK_TOOLS = [
    _tool(
        "notes",
        "Replace your notes, which every observation shows and closing a task keeps. "
        "Send the whole text each time; keep it short.",
        _object_schema(
            {
                "text": {
                    "type": "string",
                    "description": "Your current plan, what you decided while "
                    "thinking, and what you built where, with ids and world "
                    "positions.",
                }
            },
            ["text"],
        ),
    ),
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
                            "title": {
                                "type": "string",
                                "description": "A few words.",
                            },
                            "done_when": {
                                "type": "string",
                                "description": "A condition you can check in the "
                                "observations, in one sentence.",
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
                    "items": {
                        "type": "string",
                        "description": "One or two sentences.",
                    },
                },
                "reason": {
                    "type": "string",
                    "description": "Why the first approach fits the goal best, "
                    "briefly.",
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
                "result": {
                    "type": "string",
                    "description": "What was achieved, with the locations and facts "
                    "later tasks need. Keep it short.",
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
                "reason": {
                    "type": "string",
                    "description": "Why it failed and what was learned, briefly.",
                }
            },
            ["reason"],
        ),
    ),
]
TASK_TOOL_NAMES = {tool["function"]["name"] for tool in TASK_TOOLS}


def _feedback_tool(tool_names: list[str]) -> dict[str, Any]:
    return _tool(
        "feedback",
        "Report a problem with your tools, observations, instructions, or harness to "
        "the developers. It changes nothing in this run and does not stop the chain. "
        "Categories: missing_tool, an action no tool does; tool_bug, a result that "
        "contradicts the tool's description or the next observation; "
        "missing_observation, something you needed to see that no observation or "
        "lookup shows; misleading_docs, a tool worked as built but its description or "
        "your instructions led you wrong; friction, it works but takes too many calls "
        "or turns, or a limit is too tight; harness, the planning loop or context got "
        "in the way, e.g. a fact lost when a closed task's steps left your context; "
        "task_issue, the goal is ambiguous or impossible from the start. Your own "
        "mistakes are worth reporting only when the docs caused them.",
        _object_schema(
            {
                "category": {
                    "type": "string",
                    "enum": [
                        "missing_tool",
                        "tool_bug",
                        "missing_observation",
                        "misleading_docs",
                        "friction",
                        "harness",
                        "task_issue",
                    ],
                },
                "tool": {
                    "type": "string",
                    "enum": tool_names,
                    "description": "The tool concerned, if any.",
                },
                "summary": {
                    "type": "string",
                    "description": "One line naming the problem.",
                },
                "expected": {
                    "type": "string",
                    "description": "What you needed or expected, briefly.",
                },
                "observed": {
                    "type": "string",
                    "description": "What happened or was available instead, quoting "
                    "the call and result when there is one. Keep it short.",
                },
                "impact": {
                    "type": "string",
                    "enum": ["blocked", "worked_around", "minor"],
                },
                "workaround": {
                    "type": "string",
                    "description": "How you got past it, if you did, briefly.",
                },
            },
            ["category", "summary", "expected", "observed", "impact"],
        ),
    )


def tools_for(desktop: bool, api: bool) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    if desktop:
        selected.extend(DESKTOP_TOOLS)
    if api:
        selected.extend(API_TOOLS)
    if desktop and api:
        selected.extend(MIXED_TOOLS)
    selected.extend(TASK_TOOLS)
    selected.append(_feedback_tool([tool["function"]["name"] for tool in selected]))
    return selected


def execute_tool(
    computer: Computer | None,
    factorio: FactorioAPI | None,
    name: str,
    arguments: dict[str, Any],
) -> str:
    if name in TASK_TOOL_NAMES or name == "feedback":
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
