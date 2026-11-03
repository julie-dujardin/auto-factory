from __future__ import annotations

import json
from typing import Any

from .computer import NORMALIZED_SCREEN_SIZE, Computer, Screenshot
from .factorio import FactorioAPI

# The camera is centred on the player and draws a tile 32 pixels wide at zoom 1.
TILE_PIXELS = 32
# Three pointer steps per tile, so the game sees every tile the drag crosses.
SECONDS_PER_TILE = 0.05
# Input actions apply on later game ticks; finishing early would clear the cursor
# under the drag.
SETTLE_SECONDS = 0.25


def _screen_point(
    offset: dict[str, float], zoom: float, screen: Screenshot
) -> tuple[int, int]:
    scale = TILE_PIXELS * zoom
    x = screen.width / 2 + offset["dx"] * scale
    y = screen.height / 2 + offset["dy"] * scale
    return (
        round(x / screen.width * NORMALIZED_SCREEN_SIZE),
        round(y / screen.height * NORMALIZED_SCREEN_SIZE),
    )


def visible_offsets(camera: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """The dx and dy ranges of the game view, from the mod's camera method."""
    scale = TILE_PIXELS * camera["zoom"]
    half_dx = camera["resolution"]["width"] / 2 / scale
    half_dy = camera["resolution"]["height"] / 2 / scale
    dx, dy = camera["centre"]["dx"], camera["centre"]["dy"]
    return {
        "dx": (round(dx - half_dx, 1), round(dx + half_dx, 1)),
        "dy": (round(dy - half_dy, 1), round(dy + half_dy, 1)),
    }


def drag_build(
    computer: Computer,
    factorio: FactorioAPI,
    item: str,
    dx: float,
    dy: float,
    direction: str,
    count: int,
) -> str:
    plan = factorio.call(
        "drag_prepare",
        {"item": item, "dx": dx, "dy": dy, "direction": direction, "count": count},
    )
    try:
        screen = computer.screenshot()
        width, height = plan["resolution"]["width"], plan["resolution"]["height"]
        if (width, height) != (screen.width, screen.height):
            raise RuntimeError(
                f"Factorio renders at {width}x{height} but the screen is "
                f"{screen.width}x{screen.height}; run it fullscreen."
            )
        computer.wait(SETTLE_SECONDS)
        computer.drag(
            *_screen_point(plan["start"], plan["zoom"], screen),
            *_screen_point(plan["finish"], plan["zoom"], screen),
            "left",
            plan["tiles"] * SECONDS_PER_TILE,
        )
        computer.wait(SETTLE_SECONDS)
    finally:
        result = factorio.call("drag_finish", {})
    return json.dumps(result, separators=(",", ":"))
