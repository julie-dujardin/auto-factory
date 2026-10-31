from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any, Protocol

from ..control.computer import Computer, Screenshot
from ..control.factorio import FactorioAPI
from .tools import ControlMode, execute_tool, tools_for_mode


SYSTEM_PROMPT = """You are controlling Factorio through observations and tools.
Work toward the user's goal in small, deliberate steps. Inspect the newest observations
before acting. Screenshot coordinates are normalized to [0, 1000] with the origin at
top-left. Game-state coordinates are absolute Factorio world coordinates.
Use game_action for known controls instead of reasoning about keyboard letters.
Use click with the right button and a hold duration to mine resources or entities.
API actions enforce normal reach, inventory, collision, mining, and crafting constraints.
After an action, use the next observations to verify its effect. Call answer only when
the goal is complete or cannot be completed.
"""


MODE_PROMPTS: dict[ControlMode, str] = {
    "computer": "Use the screenshot and desktop tools.",
    "api": "Use structured game state and API tools; no screenshot is available.",
    "mixed": "Use either desktop or API tools, choosing the most reliable option per step.",
}


class ChatCompletions(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


def observation(screenshot: Screenshot) -> dict[str, Any]:
    encoded = base64.b64encode(screenshot.png).decode("ascii")
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": "<observation>\n"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            },
            {"type": "text", "text": "\n</observation>"},
        ],
    }


def game_state_observation(state: dict[str, Any]) -> dict[str, str]:
    return {
        "role": "user",
        "content": "<game_state>\n"
        + json.dumps(state, separators=(",", ":"))
        + "\n</game_state>",
    }


def trim_images(messages: list[dict[str, Any]], keep: int = 3) -> None:
    seen = 0
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") != "image_url":
                continue
            seen += 1
            if seen > keep:
                part.clear()
                part.update({"type": "text", "text": "[screenshot evicted]"})


def trim_game_states(messages: list[dict[str, Any]], keep: int = 3) -> None:
    seen = 0
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, str):
            continue
        if not content.startswith("<game_state>\n"):
            continue
        seen += 1
        if seen > keep:
            message["content"] = (
                "<game_state>\n[structured observation evicted]\n</game_state>"
            )


class FactorioAgent:
    def __init__(
        self,
        completions: ChatCompletions,
        computer: Computer | None,
        model: str,
        factorio: FactorioAPI | None = None,
        control: ControlMode = "computer",
        observation_radius: float = 12,
        max_steps: int = 100,
        report: Callable[[str], None] = print,
    ) -> None:
        if control in {"computer", "mixed"} and computer is None:
            raise ValueError(f"{control} mode requires computer control")
        if control in {"api", "mixed"} and factorio is None:
            raise ValueError(f"{control} mode requires Factorio API control")
        self._completions = completions
        self._computer = computer
        self._factorio = factorio
        self._model = model
        self._control = control
        self._observation_radius = observation_radius
        self._max_steps = max_steps
        self._report = report
        self._tools = tools_for_mode(control)

    def run(self, task: str) -> str:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT + "\n" + MODE_PROMPTS[self._control],
            },
            {"role": "user", "content": task},
        ]

        for step in range(1, self._max_steps + 1):
            if self._computer is not None:
                messages.append(observation(self._computer.screenshot()))
            if self._factorio is not None:
                state = self._factorio.observe(self._observation_radius)
                messages.append(game_state_observation(state))
            trim_images(messages)
            trim_game_states(messages)
            response = self._completions.create(
                model=self._model,
                messages=messages,
                tools=self._tools,
                tool_choice="required",
                temperature=0.8,
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [call.model_dump(exclude_none=True) for call in tool_calls],
                }
            )
            if not tool_calls:
                self._report(f"step {step}: model returned no tool call")
                continue

            for call in tool_calls:
                name = call.function.name
                try:
                    arguments = json.loads(call.function.arguments)
                except json.JSONDecodeError as exc:
                    result = f"error: invalid JSON arguments: {exc}"
                else:
                    self._report(f"step {step}: {name} {arguments}")
                    if name == "answer":
                        return str(arguments["content"])
                    try:
                        result = execute_tool(
                            self._computer,
                            self._factorio,
                            name,
                            arguments,
                        )
                    except (RuntimeError, TypeError, ValueError) as exc:
                        result = f"error: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )

        return f"Step budget exhausted after {self._max_steps} steps."
