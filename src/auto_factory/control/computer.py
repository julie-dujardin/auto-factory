from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

NORMALIZED_SCREEN_SIZE = 1000
# A few frames, so the game reads the press and the final position at rest.
DRAG_SETTLE_SECONDS = 0.05


FACTORIO_KEYS: dict[str, tuple[str, ...]] = {
    "move_up": ("w",),
    "move_down": ("s",),
    "move_left": ("a",),
    "move_right": ("d",),
    "open_inventory": ("e",),
    "pick_up_items": ("f",),
    "drop_item": ("z",),
    "rotate_clockwise": ("r",),
    "rotate_counterclockwise": ("shift", "r"),
    "clear_cursor": ("q",),
    "open_map": ("m",),
    "toggle_alt_mode": ("alt",),
    "shoot": ("space",),
    "confirm": ("enter",),
    "cancel": ("esc",),
    "pause": ("shift", "space"),
    "quickbar_1": ("1",),
    "quickbar_2": ("2",),
    "quickbar_3": ("3",),
    "quickbar_4": ("4",),
    "quickbar_5": ("5",),
    "quickbar_6": ("6",),
    "quickbar_7": ("7",),
    "quickbar_8": ("8",),
    "quickbar_9": ("9",),
    "quickbar_10": ("0",),
}


@dataclass(frozen=True)
class Screenshot:
    png: bytes
    width: int
    height: int


class Screen(Protocol):
    def screenshot(self) -> Screenshot: ...


class Computer(Screen, Protocol):
    def game_action(self, action: str, duration: float) -> None: ...

    def type_text(self, text: str, interval: float) -> None: ...

    def move_cursor(self, x: int, y: int, duration: float) -> None: ...

    def click(
        self,
        x: int,
        y: int,
        button: str,
        clicks: int,
        hold_seconds: float,
    ) -> None: ...

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str,
        duration: float,
    ) -> None: ...

    def scroll(self, x: int, y: int, amount: int) -> None: ...

    def wait(self, seconds: float) -> None: ...


def normalized_to_pixel(value: int, size: int) -> int:
    if not 0 <= value <= NORMALIZED_SCREEN_SIZE:
        raise ValueError(f"coordinate {value} is outside [0, 1000]")
    if size < 1:
        raise ValueError("screen dimensions must be positive")
    return min(size - 1, int(value / NORMALIZED_SCREEN_SIZE * size))


class WindowScreen:
    """Captures the Factorio window on macOS, even when other windows cover it."""

    def __init__(self) -> None:
        try:
            # PyObjC creates framework symbols lazily, out of type checkers' sight.
            quartz: Any = importlib.import_module("Quartz")
        except ImportError as exc:
            raise RuntimeError(
                "Window capture dependencies are unavailable; run `uv sync`."
            ) from exc
        # Prompts for the permission the first time.
        if not quartz.CGRequestScreenCaptureAccess():
            raise RuntimeError(
                "Grant your terminal Screen Recording in System Settings > "
                "Privacy & Security, then retry."
            )
        self._quartz = quartz

    def screenshot(self) -> Screenshot:
        quartz = self._quartz
        windows = quartz.CGWindowListCopyWindowInfo(
            quartz.kCGWindowListOptionAll, quartz.kCGNullWindowID
        )
        # Factorio also owns thin menu-bar windows on every display.
        game = max(
            (
                window
                for window in windows
                if str(window.get("kCGWindowOwnerName", "")).startswith("Factorio")
                and window.get("kCGWindowLayer") == 0
            ),
            key=lambda window: (
                window["kCGWindowBounds"]["Width"] * window["kCGWindowBounds"]["Height"]
            ),
            default=None,
        )
        if game is None:
            raise RuntimeError("Factorio is not running; run `auto-factory-game`.")

        # Nominal resolution: one pixel per point, so Retina captures stay small.
        image = quartz.CGWindowListCreateImage(
            quartz.CGRectNull,
            quartz.kCGWindowListOptionIncludingWindow,
            game["kCGWindowNumber"],
            quartz.kCGWindowImageBoundsIgnoreFraming
            | quartz.kCGWindowImageNominalResolution,
        )
        if image is None:
            raise RuntimeError("Could not capture the Factorio window.")
        data = quartz.CFDataCreateMutable(None, 0)
        destination = quartz.CGImageDestinationCreateWithData(
            data, "public.png", 1, None
        )
        quartz.CGImageDestinationAddImage(destination, image, None)
        if not quartz.CGImageDestinationFinalize(destination):
            raise RuntimeError("Could not encode the Factorio window capture.")
        return Screenshot(
            png=bytes(data),
            width=quartz.CGImageGetWidth(image),
            height=quartz.CGImageGetHeight(image),
        )


class DesktopComputer:
    def __init__(self, display: str) -> None:
        try:
            import mss
            from mss.exception import ScreenShotError
        except ImportError as exc:
            raise RuntimeError(
                "Desktop control dependencies are unavailable; run `uv sync`."
            ) from exc

        try:
            self._mss = mss.MSS(display=display)
        except ScreenShotError as exc:
            raise RuntimeError(
                f"Could not open DISPLAY={display}; run `auto-factory-game` first."
            ) from exc
        if len(self._mss.monitors) < 2:
            raise RuntimeError(f"No monitor is available on DISPLAY={display}.")
        self._monitor = self._mss.monitors[1]

        previous_display = os.environ.get("DISPLAY")
        os.environ["DISPLAY"] = display
        try:
            from pynput import keyboard, mouse

            self._keyboard_module = keyboard
            self._mouse_module = mouse
            self._keyboard = keyboard.Controller()
            self._mouse = mouse.Controller()
        except ImportError as exc:
            raise RuntimeError(
                "Desktop control dependencies are unavailable; run `uv sync`."
            ) from exc
        finally:
            if previous_display is None:
                os.environ.pop("DISPLAY", None)
            else:
                os.environ["DISPLAY"] = previous_display
        self._last_screenshot: Screenshot | None = None

    def screenshot(self) -> Screenshot:
        from mss.tools import to_png

        shot = self._mss.grab(self._monitor)
        png = to_png(shot.rgb, shot.size)
        if png is None:
            raise RuntimeError("Desktop capture did not produce an image.")
        screenshot = Screenshot(
            png=png,
            width=shot.width,
            height=shot.height,
        )
        self._last_screenshot = screenshot
        return screenshot

    def game_action(self, action: str, duration: float) -> None:
        keys = FACTORIO_KEYS.get(action)
        if keys is None:
            raise ValueError(f"unknown Factorio action: {action}")
        duration = self._bounded(duration, 0.0, 10.0, "duration")
        resolved = [self._resolve_key(key) for key in keys]
        for key in resolved:
            self._keyboard.press(key)
        try:
            time.sleep(duration)
        finally:
            for key in reversed(resolved):
                self._keyboard.release(key)

    def type_text(self, text: str, interval: float) -> None:
        if len(text) > 500:
            raise ValueError("text is limited to 500 characters")
        interval = self._bounded(interval, 0.0, 2.0, "interval")
        self._keyboard.type(text)
        if interval:
            time.sleep(interval)

    def move_cursor(self, x: int, y: int, duration: float) -> None:
        target = self._point(x, y)
        duration = self._bounded(duration, 0.0, 5.0, "duration")
        if duration == 0:
            self._mouse.position = target
            return

        start_x, start_y = self._mouse.position
        steps = max(1, round(duration * 60))
        for step in range(1, steps + 1):
            ratio = step / steps
            self._mouse.position = (
                round(start_x + (target[0] - start_x) * ratio),
                round(start_y + (target[1] - start_y) * ratio),
            )
            time.sleep(duration / steps)

    def click(
        self,
        x: int,
        y: int,
        button: str,
        clicks: int,
        hold_seconds: float,
    ) -> None:
        self.move_cursor(x, y, 0)
        hold_seconds = self._bounded(hold_seconds, 0.0, 10.0, "hold_seconds")
        if not 1 <= clicks <= 3:
            raise ValueError("clicks must be between 1 and 3")
        mouse_button = self._resolve_button(button)
        for _ in range(clicks):
            self._mouse.press(mouse_button)
            try:
                time.sleep(hold_seconds)
            finally:
                self._mouse.release(mouse_button)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str,
        duration: float,
    ) -> None:
        self.move_cursor(start_x, start_y, 0)
        mouse_button = self._resolve_button(button)
        self._mouse.press(mouse_button)
        try:
            time.sleep(DRAG_SETTLE_SECONDS)
            self.move_cursor(end_x, end_y, duration)
            time.sleep(DRAG_SETTLE_SECONDS)
        finally:
            self._mouse.release(mouse_button)

    def scroll(self, x: int, y: int, amount: int) -> None:
        if not -20 <= amount <= 20:
            raise ValueError("scroll amount must be between -20 and 20")
        self.move_cursor(x, y, 0)
        self._mouse.scroll(0, amount)

    def wait(self, seconds: float) -> None:
        time.sleep(self._bounded(seconds, 0.0, 30.0, "seconds"))

    def _point(self, x: int, y: int) -> tuple[int, int]:
        screenshot = self._last_screenshot
        if screenshot is None:
            raise RuntimeError("capture a screenshot before using pointer tools")
        return (
            normalized_to_pixel(x, screenshot.width),
            normalized_to_pixel(y, screenshot.height),
        )

    def _resolve_key(self, name: str) -> Any:
        special = {
            "alt": self._keyboard_module.Key.alt,
            "enter": self._keyboard_module.Key.enter,
            "esc": self._keyboard_module.Key.esc,
            "shift": self._keyboard_module.Key.shift,
            "space": self._keyboard_module.Key.space,
        }
        return special.get(name, name)

    def _resolve_button(self, name: str) -> Any:
        buttons = {
            "left": self._mouse_module.Button.left,
            "middle": self._mouse_module.Button.middle,
            "right": self._mouse_module.Button.right,
        }
        try:
            return buttons[name]
        except KeyError as exc:
            raise ValueError(f"unknown mouse button: {name}") from exc

    @staticmethod
    def _bounded(value: float, minimum: float, maximum: float, name: str) -> float:
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return value
