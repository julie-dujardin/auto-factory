from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any, Literal

from langfuse import get_client

from ..control.computer import Computer, Screen, Screenshot
from ..control.drag import visible_offsets
from ..control.factorio import FactorioAPI
from .tasks import Task, TaskTree
from .tools import (
    TASK_TOOL_NAMES,
    ControlMode,
    execute_tool,
    tools_for,
)

SYSTEM_PROMPT = """You are controlling Factorio through observations and tools.
Work toward the user's goal in deliberate steps. Inspect the newest observations
before acting. Screenshot coordinates are normalized to [0, 1000] with the origin at
top-left. Game positions in API arguments and results are dx/dy offsets in tiles from
the centre of the tile the player stood on when the run started (positive dx is east,
positive dy is south). They stay fixed as the player moves, so a position from any
earlier result or note can be passed straight back; player.position in api_scan is
where the player stands now. An entity's position is its centre, a half offset along
an even side. Entities larger than one tile also give area: the tiles they cover, as
inclusive dx and dy ranges. A 3x3 machine at dx=1 dy=1 has area dx [0, 2] and
dy [0, 2], a 2x2 one at dx=0.5 dy=0.5 has dx [0, 1] and dy [0, 1]; messages write
these dx=0..2 dy=0..2. Supply, mining, and patch areas come as the same ranges.
Entity ids from api_scan, api_find, api_place, and api_connect never change, so prefer
them for entities you act on or build next to.
Use game_action for known controls instead of reasoning about keyboard letters.
Use click with the right button and a hold duration to mine resources or entities.
API actions enforce normal reach, inventory, collision, mining, and crafting constraints.
The player builds, reaches entities, and mines resource tiles only within the
build_distance, reach_distance, and resource_reach_distance api_scan gives for the
player; walk closer before acting.
Research of type "trigger" completes automatically when the required action occurs
(producing items, etc), without needing to be queued.

Avoid manual actions: prefer using machines rather than performing manual actions like mining.

Never guess game information. Your memory of ingredients, amounts, crafting times, machines,
thier dimensions, and unlock state is unreliable; api_recipe is the source of truth. Look up the goal's
items and their ingredients with api_recipe before planning, and again for every new
item you plan to craft, smelt, or build. Likewise never guess an entity's size or
where it takes and puts items and fluids: look it up with api_entity_info before
laying out machines, inserters, belts, or pipes. Lookups are cheap and run together,
so make them in bulk: in one turn, call api_recipe for every item involved and
api_entity_info for every entity you may place, inserters and poles included.
As soon as you know what you'll be working with, lookup the entities, recipes, machines, etc,
in one single bulk run, before starting to plan.

Never guess an ID either. When unsure of the exact name of an item, fluid, recipe,
entity, entity type, or entity status, find it with api_search; for a technology, use
api_technologies. An error for an unknown ID lists similar IDs: pick from them or
search, never retry a variant.

Your thinking is not shown to you again, so keep your plan in notes: whenever thinking
settles a plan, a layout, or a fix, write it with notes in the same turn as your first
action on it, and record what you built where, with ids and positions.
For a goal with several stages, split it into ordered tasks with add_tasks; a simple
goal needs none. propose_approaches gives the current task fallbacks that fail_task
moves to in order. Call complete_task when its done_when holds, recording the
locations and facts later tasks need: a closed task's steps are removed from your
context. Call fail_task when an approach does not work, saying what you learned.
Completing or failing the goal ends the run.

Every turn is slow: return every tool call you can already decide in one turn, e.g.
one api_take per full furnace in reach, or api_walk_to then api_place. They run in
order; the chain stops after an error, a blocked walk, a partial placement,
complete_task, or fail_task, and skips the calls after it. Use the next observations
to verify the chain's effect.

Keep each turn's thinking short: a turn that thinks too long is cut off before it
calls a tool. When a plan grows long, record what you have decided with notes and work
out each part in its own turn.

When a tool is missing, broken, or misleading, when you cannot see something you need,
or when the planning loop gets in your way, report it with feedback alongside your next
action, then carry on with a workaround. Never report instead of acting.

A transport belt moves items the way it faces, on two lanes. Each tile feeds only the
tile in front of it, so a belt never forks: items leave a running belt only through an
inserter or a splitter. A belt, splitter, or underground exit facing into a belt that
faces another way, other than head-on, feeds it: when it is that belt's only input, the
two form a curve that keeps both lanes; otherwise its items all go onto the lane on the
side they enter (sideloading). To turn a line, start the next run on the tile ahead of
the last one's end, facing the new way. api_place's belt_from and belt_to show what a
new belt joined.

An inserter moves items in a straight line across its own tile: it takes from the tile
on one side and drops onto the tile on the opposite side, 1 tile away (2 for
long-handed). Its direction is the side it takes from: one at dy=0 facing north takes
from dy=-1 and drops into dy=1. So an inserter that is not long-handed needs exactly one
free tile between the two things it links, and stands there. takes_from and gives_to
give the tile it reaches on each side.

A splitter is 2 tiles wide across the flow and 1 long; give api_place the point
between its two tiles. It splits the items entering its back evenly between the two
tiles in front, keeping each item on its lane, and sends everything to one side when
the other backs up. Placed over one belt and a free tile, it branches that belt from
the free half; placed over two belts, it mixes their items. Splitters and underground
belts can be placed over existing belts, which return to the inventory.

An underground belt pair carries a belt under anything, with up to 4 tiles between
its ends (6 fast, 8 express, 10 turbo). Place the entrance before the obstacle and the
exit after it with separate api_place calls, both facing the flow: the second becomes
the exit of the nearest entrance of the same tier facing the same way behind it.
api_scan shows a pair as one part of its belt line, or no exit if an entrance has none.

A pipe-to-ground pair carries fluid under anything, with up to 9 tiles between its
ends. Each end faces its above-ground pipe connection and connects underground on the
opposite side, so the two ends of a pair face away from each other. api_scan shows
where each end's pair is.
"""


MODE_PROMPTS: dict[ControlMode, str] = {
    "computer": "Use the screenshot and desktop tools.",
    "api": "Use structured game state and API tools; no screenshot is available.",
    "mixed": "Use either desktop or API tools, choosing the most reliable option per step.",
}
# Mixed control on macOS, where only the window can be captured.
SCREEN_ONLY_PROMPT = (
    "Use the screenshot and structured game state to see, and API tools to act."
)
# The truncated reasoning is not sent back, so the next turn would start over.
CUT_OFF_WARNING = {
    "role": "user",
    "content": "Your last turn hit the output limit while thinking, before it called "
    "a tool, and its thinking is lost. Think less per turn: record what you have "
    "decided with notes, then work out one part at a time.",
}
CUT_OFF_NOTED = {
    "role": "user",
    "content": "Your last turn hit the output limit while thinking, before it called "
    "a tool; what it worked out is now in your notes. Think less per turn: work out "
    "one part at a time.",
}


def cut_off_thinking(reasoning: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": "Your last turn hit the output limit while thinking, before it "
        "called a tool. This is its thinking, which you will not see again:\n"
        f"<thinking>\n{reasoning}\n</thinking>\n"
        "Save with notes what it settled that you still need: the plan, layout, or "
        "fix, with the ids and positions involved, keeping what still holds from "
        "your current notes. Where it changed its mind, keep only its last "
        "conclusion.",
    }


CUT_OFF_CALL = (
    "error: the output limit cut this call off while you wrote its arguments, so it "
    "did not run; send it again with shorter arguments"
)
MAX_REPORTS = 10

ReasoningEffort = Literal["low", "medium", "xhigh"]
# holo4-27b's levels, lowest first; other Holo models accept and ignore them.
REASONING_EFFORTS: tuple[ReasoningEffort, ...] = ("low", "medium", "xhigh")


def lower_effort(effort: ReasoningEffort) -> ReasoningEffort:
    return REASONING_EFFORTS[max(0, REASONING_EFFORTS.index(effort) - 1)]


def look_back_prompt(outcome: str, reports: list[str]) -> dict[str, str]:
    reported = "".join(f"\n- {summary}" for summary in reports) or " none"
    return {
        "role": "user",
        "content": f"The run is over: {outcome}\nLook back over the whole run and "
        "report with feedback each problem with your tools, observations, "
        "instructions, or harness that you have not reported yet, up to "
        f"{MAX_REPORTS - len(reports)} more. If there is none, reply without a tool "
        f"call. Already reported:{reported}",
    }


def observation(
    screenshot: Screenshot, camera: dict[str, Any] | None = None
) -> dict[str, Any]:
    encoded = base64.b64encode(screenshot.png).decode("ascii")
    header = "<observation>\n"
    if camera is not None:
        offsets = visible_offsets(camera)
        (left, right), (top, bottom) = offsets["dx"], offsets["dy"]
        header += (
            f"The game view spans dx {left} to {right} and dy {top} to {bottom}.\n"
        )
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": header},
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


def trim_images(messages: list[dict[str, Any]], keep: int = 1) -> None:
    seen = 0
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        seen += 1
        if seen > keep:
            message["content"] = "<observation>\n[screenshot evicted]\n</observation>"


def tasks_observation(tasks: TaskTree) -> dict[str, str]:
    return {"role": "user", "content": f"<tasks>\n{tasks.render()}\n</tasks>"}


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


def trim_tasks(messages: list[dict[str, Any]]) -> None:
    _trim_tagged(messages, "tasks", "superseded by later tasks", keep=1)


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


def tool_result(call: Any, content: str) -> dict[str, str]:
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def fell_short(name: str, result: str) -> bool:
    if name == "api_walk_to":
        return json.loads(result).get("reason") != "arrived"
    if name in {"api_place", "api_connect", "drag_build"}:
        return "stopped" in json.loads(result)
    return False


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
        reasoning_effort: ReasoningEffort = "medium",
        report: Callable[[str], None] = print,
        screen: Screen | None = None,
    ) -> None:
        if control == "computer" and computer is None:
            raise ValueError("computer mode requires computer control")
        if control in {"api", "mixed"} and factorio is None:
            raise ValueError(f"{control} mode requires Factorio API control")
        self._screen = computer if screen is None else screen
        if control == "mixed" and self._screen is None:
            raise ValueError("mixed mode requires screenshots")
        self._create_completion = create_completion
        self._computer = computer
        self._factorio = factorio
        self._model = model
        self._mode_prompt = (
            SCREEN_ONLY_PROMPT
            if control == "mixed" and computer is None
            else MODE_PROMPTS[control]
        )
        self._observation_radius = observation_radius
        self._max_steps = max_steps
        self._reasoning_effort = reasoning_effort
        self._report = report
        self._tools = tools_for(desktop=computer is not None, api=factorio is not None)

    def run(self, task: str, scenario: str | None = None) -> str:
        """scenario describes the world the run starts in, apart from the goal."""
        prompt = (
            task
            if scenario is None
            else f"<scenario>\n{scenario}\n</scenario>\n\n{task}"
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT + "\n" + self._mode_prompt,
            },
            {"role": "user", "content": prompt},
        ]
        tasks = TaskTree(task)
        reports: list[str] = []
        if self._factorio is not None:
            self._factorio.call("set_origin", {})
        outcome = self._play(messages, tasks, reports)
        self._look_back(messages, tasks, reports, outcome)
        return outcome

    def _play(
        self, messages: list[dict[str, Any]], tasks: TaskTree, reports: list[str]
    ) -> str:
        # Where each task's steps begin, so closing it can drop them.
        starts: dict[Task, int] = {}
        # The latest other call, attached to feedback as evidence.
        last_call: dict[str, Any] | None = None
        # A turn cut off while thinking is retried one level lower, until one acts.
        effort = self._reasoning_effort

        for step in range(1, self._max_steps + 1):
            starts.setdefault(tasks.current, len(messages))
            if self._screen is not None:
                camera = (
                    None
                    if self._factorio is None
                    else self._factorio.call("camera", {})
                )
                messages.append(observation(self._screen.screenshot(), camera))
            if self._factorio is not None:
                state = self._factorio.observe(self._observation_radius)
                messages.append(game_state_observation(state))
            messages.append(tasks_observation(tasks))
            trim_images(messages)
            trim_game_states(messages)
            trim_tasks(messages)
            tool_calls, cut_off, reasoning = self._complete(
                f"step {step}", messages, self._tools, "required", effort
            )
            if cut_off and not tool_calls:
                effort = lower_effort(effort)
                self._report(
                    f"step {step}: output limit hit before a tool call; "
                    f"retrying at {effort} reasoning effort"
                )
                self._save_cut_off_thinking(messages, tasks, step, reasoning)
                continue
            if not tool_calls:
                self._report(f"step {step}: model returned no tool call")
                continue
            effort = self._reasoning_effort

            cut: int | None = None
            calls = iter(tool_calls)
            for call in calls:
                name = call.function.name
                # The server may still parse the unfinished last call, e.g. as {}.
                if cut_off and call is tool_calls[-1]:
                    self._report(f"step {step}: {name} cut off by the output limit")
                    messages.append(tool_result(call, CUT_OFF_CALL))
                    break
                try:
                    arguments = json.loads(call.function.arguments)
                except json.JSONDecodeError as exc:
                    result = f"error: invalid JSON arguments: {exc}"
                    stop = True
                else:
                    self._report(f"step {step}: {name} {arguments}")
                    with get_client().start_as_current_observation(
                        as_type="tool", name=name, input=arguments
                    ) as span:
                        acted = tasks.current
                        try:
                            if name == "feedback":
                                result = self._feedback(
                                    span, reports, arguments, last_call
                                )
                            else:
                                result = self._execute(tasks, name, arguments)
                        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
                            result = f"error: {exc}"
                            span.update(level="ERROR", status_message=str(exc))
                            stop = True
                        else:
                            if name in {"complete_task", "fail_task"}:
                                cut = starts.pop(acted, None)
                                stop = True
                            else:
                                stop = fell_short(name, result)
                        span.update(output=result)
                    if name != "feedback":
                        last_call = {
                            "tool": name,
                            "arguments": arguments,
                            "result": result,
                        }
                messages.append(tool_result(call, result))
                if stop:
                    break
            for call in calls:
                self._report(f"step {step}: skipped {call.function.name}")
                messages.append(
                    tool_result(call, "skipped: the chain stopped at an earlier call")
                )
            # The look back needs the run's context, so the goal's steps stay.
            if tasks.finished:
                return tasks.outcome
            if cut is not None:
                del messages[cut:]

        return f"Step budget exhausted after {self._max_steps} steps."

    def _complete(
        self,
        name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str,
        reasoning_effort: ReasoningEffort,
    ) -> tuple[list[Any], bool, str | None]:
        """Request one turn, append it to messages, and give its tool calls, whether
        the output limit cut it off, and its reasoning."""
        parameters: dict[str, str | float] = {
            "tool_choice": tool_choice,
            "temperature": 0.8,
            "reasoning_effort": reasoning_effort,
        }
        with get_client().start_as_current_observation(
            as_type="generation",
            name=name,
            model=self._model,
            input=messages,
            model_parameters=dict(parameters),
        ) as generation:
            response = self._create_completion(
                model=self._model,
                messages=messages,
                tools=tools,
                **parameters,
            )
            choice = response.choices[0]
            message = choice.message
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
            cut_off = choice.finish_reason == "length"
            if cut_off:
                generation.update(
                    level="WARNING",
                    status_message="output limit in the last tool call"
                    if tool_calls
                    else "output limit before a tool call",
                )
        messages.append(reply)
        return tool_calls, cut_off, getattr(message, "reasoning", None)

    def _save_cut_off_thinking(
        self,
        messages: list[dict[str, Any]],
        tasks: TaskTree,
        step: int,
        reasoning: str | None,
    ) -> None:
        """Have the model save to notes what a turn cut off while thinking worked
        out, then drop that thinking from the context."""
        start = len(messages)
        saved = False
        if reasoning:
            messages.append(cut_off_thinking(reasoning))
            tools = [
                tool for tool in self._tools if tool["function"]["name"] == "notes"
            ]
            tool_calls, cut_off, _ = self._complete(
                f"step {step} notes", messages, tools, "required", REASONING_EFFORTS[0]
            )
            # Later calls of the turn repeat ever shorter fragments of the first, and
            # the output limit leaves the last one unfinished.
            finished = tool_calls[:-1] if cut_off else tool_calls
            try:
                arguments = json.loads(finished[0].function.arguments)
                result = tasks.handle("notes", arguments)
            except IndexError:
                pass
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                self._report(f"step {step}: notes from cut-off thinking: {exc}")
            else:
                with get_client().start_as_current_observation(
                    as_type="tool", name="notes", input=arguments
                ) as span:
                    span.update(output=result)
                saved = True
        del messages[start:]
        messages.append(CUT_OFF_NOTED if saved else CUT_OFF_WARNING)

    def _feedback(
        self,
        span: Any,
        reports: list[str],
        arguments: dict[str, Any],
        evidence: dict[str, Any] | None,
    ) -> str:
        if len(reports) >= MAX_REPORTS:
            return f"not recorded: this run's {MAX_REPORTS} reports are used up"
        reports.append(str(arguments.get("summary", "")))
        span.update(level="WARNING", metadata={"previous_call": evidence})
        return f"ok; recorded, {MAX_REPORTS - len(reports)} reports left this run"

    def _look_back(
        self,
        messages: list[dict[str, Any]],
        tasks: TaskTree,
        reports: list[str],
        outcome: str,
    ) -> None:
        """One last turn to report problems the agent did not stop for mid-run."""
        if len(reports) >= MAX_REPORTS:
            return
        messages.append(tasks_observation(tasks))
        trim_tasks(messages)
        messages.append(look_back_prompt(outcome, reports))
        tools = [tool for tool in self._tools if tool["function"]["name"] == "feedback"]
        tool_calls, _, _ = self._complete(
            "look back", messages, tools, "auto", self._reasoning_effort
        )
        for call in tool_calls:
            try:
                arguments = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                self._report(f"look back: invalid JSON in {call.function.name}")
                continue
            self._report(f"look back: {call.function.name} {arguments}")
            with get_client().start_as_current_observation(
                as_type="tool", name="feedback", input=arguments
            ) as span:
                span.update(output=self._feedback(span, reports, arguments, None))

    def _execute(self, tasks: TaskTree, name: str, arguments: dict[str, Any]) -> str:
        if name in TASK_TOOL_NAMES:
            return tasks.handle(name, arguments)
        return execute_tool(self._computer, self._factorio, name, arguments)
