from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

from langfuse import get_client

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
The player can build and interact with entities up to 10 tiles away, but must be
within about 2.7 tiles of a resource tile to mine it; walk closer before acting.
After an action, use the next observations to verify its effect. Old observations are
evicted, so use note to keep plans, locations, and lessons you will need later. Call
answer only when the goal is complete or cannot be completed.
research of type "trigger" complete automatically when the required action occurs
(producing items, etc), without needing to be queued.
"""


MODE_PROMPTS: dict[ControlMode, str] = {
    "computer": "Use the screenshot and desktop tools.",
    "api": "Use structured game state and API tools; no screenshot is available.",
    "mixed": "Use either desktop or API tools, choosing the most reliable option per step.",
}


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


def notes_observation(notes: list[str]) -> dict[str, str]:
    lines = "\n".join(f"{index}. {note}" for index, note in enumerate(notes, 1))
    return {"role": "user", "content": f"<notes>\n{lines}\n</notes>"}


def _trim_tagged(
    messages: list[dict[str, Any]], tag: str, placeholder: str, keep: int
) -> None:
    seen = 0
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, str):
            continue
        if not content.startswith(f"<{tag}>\n"):
            continue
        seen += 1
        if seen > keep:
            message["content"] = f"<{tag}>\n[{placeholder}]\n</{tag}>"


def trim_game_states(messages: list[dict[str, Any]], keep: int = 3) -> None:
    _trim_tagged(messages, "game_state", "structured observation evicted", keep)


def trim_notes(messages: list[dict[str, Any]]) -> None:
    # Every notes message is a superset of the earlier ones.
    _trim_tagged(messages, "notes", "superseded by later notes", keep=1)


def thinking(message: Any) -> dict[str, Any]:
    # Holo returns reasoning in a non-standard field; Langfuse only renders
    # its ChatML `thinking` parts as formatted reasoning.
    reasoning = getattr(message, "reasoning", None)
    if not reasoning:
        return {}
    return {"thinking": [{"type": "thinking", "content": reasoning}]}


def usage_details(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {"input": usage.prompt_tokens, "output": usage.completion_tokens}


class FactorioAgent:
    def __init__(
        self,
        create_completion: Callable[..., Any],
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
        self._create_completion = create_completion
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
        notes: list[str] = []

        for step in range(1, self._max_steps + 1):
            if self._computer is not None:
                messages.append(observation(self._computer.screenshot()))
            if self._factorio is not None:
                state = self._factorio.observe(self._observation_radius)
                messages.append(game_state_observation(state))
            if notes:
                messages.append(notes_observation(notes))
            trim_images(messages)
            trim_game_states(messages)
            trim_notes(messages)
            parameters: dict[str, str | float] = {
                "tool_choice": "required",
                "temperature": 0.8,
            }
            with get_client().start_as_current_observation(
                as_type="generation",
                name=f"step {step}",
                model=self._model,
                input=messages,
                model_parameters=dict(parameters),
            ) as generation:
                response = self._create_completion(
                    model=self._model,
                    messages=messages,
                    tools=self._tools,
                    **parameters,
                )
                message = response.choices[0].message
                tool_calls = message.tool_calls or []
                reply = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        call.model_dump(exclude_none=True) for call in tool_calls
                    ],
                }
                generation.update(
                    output=reply | thinking(message),
                    usage_details=usage_details(response),
                )
            messages.append(reply)
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
                    with get_client().start_as_current_observation(
                        as_type="tool", name=name, input=arguments
                    ) as span:
                        try:
                            if name == "note":
                                notes.append(str(arguments["content"]))
                                result = "ok"
                            else:
                                result = execute_tool(
                                    self._computer,
                                    self._factorio,
                                    name,
                                    arguments,
                                )
                        except (RuntimeError, TypeError, ValueError) as exc:
                            result = f"error: {exc}"
                            span.update(level="ERROR", status_message=str(exc))
                        span.update(output=result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )

        return f"Step budget exhausted after {self._max_steps} steps."
