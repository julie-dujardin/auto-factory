import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from auto_factory.control.computer import Screenshot
from auto_factory.harness.agent import (
    CUT_OFF_CALL,
    CUT_OFF_NOTED,
    CUT_OFF_WARNING,
    FactorioAgent,
    fell_short,
    game_state_observation,
    observation,
    tasks_observation,
    thinking,
    trim_game_states,
    trim_images,
    trim_tasks,
    usage_details,
)
from auto_factory.harness.tasks import TaskTree
from auto_factory.harness.tools import execute_tool, tools_for


class FakeCall:
    def __init__(self, name: str, arguments: str, call_id: str = "call-1") -> None:
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self, exclude_none: bool = True) -> dict[str, object]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.function.name,
                "arguments": self.function.arguments,
            },
        }


class CutOff(list[FakeCall]):
    """Calls of a turn the output limit cut off in its last call."""


class FakeCompletions:
    def __init__(self, calls: list[FakeCall | list[FakeCall] | str]) -> None:
        self.calls = calls
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        # The agent keeps mutating its message list after each request.
        self.requests.append(deepcopy(kwargs))
        if not self.calls:
            # The look back, with nothing to report.
            message = SimpleNamespace(content="nothing", tool_calls=None)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="stop")]
            )
        calls = self.calls.pop(0)
        # A string stands for a turn cut off while thinking it, an empty list for one
        # cut off with no reasoning returned.
        reasoning = calls if isinstance(calls, str) else None
        if reasoning is not None:
            tool_calls = []
        else:
            tool_calls = calls if isinstance(calls, list) else [calls]
        message = SimpleNamespace(
            content=None, tool_calls=tool_calls, reasoning=reasoning
        )
        cut_off = not tool_calls or isinstance(calls, CutOff)
        finish_reason = "length" if cut_off else "tool_calls"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=finish_reason)]
        )


class FakeComputer:
    def __init__(self) -> None:
        self.actions: list[tuple[str, tuple[object, ...]]] = []

    def screenshot(self) -> Screenshot:
        return Screenshot(b"png", 1920, 1080)

    def game_action(self, action: str, duration: float) -> None:
        self.actions.append(("game_action", (action, duration)))

    def type_text(self, text: str, interval: float) -> None:
        self.actions.append(("type_text", (text, interval)))

    def move_cursor(self, x: int, y: int, duration: float) -> None:
        self.actions.append(("move_cursor", (x, y, duration)))

    def click(
        self, x: int, y: int, button: str, clicks: int, hold_seconds: float
    ) -> None:
        self.actions.append(("click", (x, y, button, clicks, hold_seconds)))

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str,
        duration: float,
    ) -> None:
        self.actions.append(
            ("drag", (start_x, start_y, end_x, end_y, button, duration))
        )

    def scroll(self, x: int, y: int, amount: int) -> None:
        self.actions.append(("scroll", (x, y, amount)))

    def wait(self, seconds: float) -> None:
        self.actions.append(("wait", (seconds,)))


CAMERA = {
    "centre": {"dx": 0.2, "dy": -0.4},
    "zoom": 1,
    "resolution": {"width": 1920, "height": 1088},
}


class FakeFactorio:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.actions: list[tuple[str, dict[str, object]]] = []
        self.results = {"camera": CAMERA, "set_origin": {}} | (results or {})

    def observe(self, radius: float) -> dict[str, object]:
        return {"radius": radius, "player": {"position": {"dx": 1, "dy": 2}}}

    def execute(self, name: str, arguments: dict[str, object]) -> str:
        self.actions.append((name, arguments))
        return '{"queued":1}'

    def call(self, method: str, params: dict[str, Any]) -> Any:
        self.actions.append((method, params))
        return self.results[method]


APPROACHES = '{"approaches":["a","b"],"reason":"a is best"}'
FIND = (
    '{"name":"ore","type":"resource","status":"","radius":32,"sort":"distance",'
    '"limit":5}'
)


def computer_agent(
    completions: FakeCompletions, computer: FakeComputer
) -> FactorioAgent:
    return FactorioAgent(
        completions.create, computer, "test-model", report=lambda _: None
    )


def test_agent_acts_on_an_approach_then_completes_goal() -> None:
    completions = FakeCompletions(
        [
            FakeCall("propose_approaches", APPROACHES),
            FakeCall("game_action", '{"action":"move_up","duration":0.5}'),
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )
    computer = FakeComputer()

    assert computer_agent(completions, computer).run("move") == "done"
    assert computer.actions == [("game_action", ("move_up", 0.5))]
    assert len(completions.requests) == 4


def test_scenario_precedes_the_goal() -> None:
    completions = FakeCompletions([FakeCall("complete_task", '{"result":"done"}')])

    computer_agent(completions, FakeComputer()).run("move", "A furnace stands east.")

    assert completions.requests[0]["messages"][1]["content"] == (
        "<scenario>\nA furnace stands east.\n</scenario>\n\nmove"
    )


def test_cut_off_turn_warns_to_think_less() -> None:
    completions = FakeCompletions([[], FakeCall("fail_task", '{"reason":"gave up"}')])

    assert computer_agent(completions, FakeComputer()).run("move") == "Failed: gave up"
    messages = completions.requests[1]["messages"]
    warnings = [m for m in messages if m["content"] == CUT_OFF_WARNING["content"]]
    assert len(warnings) == 1


def test_cut_off_thinking_is_saved_to_notes_then_dropped() -> None:
    completions = FakeCompletions(
        [
            "the belt goes at dy=5",
            FakeCall("notes", '{"text":"belt at dy=5"}'),
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )

    computer_agent(completions, FakeComputer()).run("move")

    noting = completions.requests[1]
    assert [tool["function"]["name"] for tool in noting["tools"]] == ["notes"]
    assert noting["reasoning_effort"] == "low"
    assert "the belt goes at dy=5" in noting["messages"][-1]["content"]
    contents = [str(m["content"]) for m in completions.requests[2]["messages"]]
    assert not any("the belt goes at dy=5" in content for content in contents)
    assert CUT_OFF_NOTED["content"] in contents
    assert "Notes:\nbelt at dy=5" in contents[-1]


def test_cut_off_note_round_falls_back_to_the_warning() -> None:
    completions = FakeCompletions(
        [
            "the belt goes at dy=5",
            "still thinking",
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )

    computer_agent(completions, FakeComputer()).run("move")

    contents = [str(m["content"]) for m in completions.requests[2]["messages"]]
    assert not any("the belt goes at dy=5" in content for content in contents)
    assert CUT_OFF_WARNING["content"] in contents
    assert "Notes: none yet" in contents[-1]


def test_cut_off_turn_retries_one_effort_lower_until_one_acts() -> None:
    completions = FakeCompletions(
        [
            [],
            [],
            [],
            FakeCall("game_action", '{"action":"move_up","duration":0.5}'),
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )
    agent = FactorioAgent(
        completions.create,
        FakeComputer(),
        "test-model",
        reasoning_effort="xhigh",
        report=lambda _: None,
    )

    agent.run("move")

    efforts = [request["reasoning_effort"] for request in completions.requests]
    assert efforts == ["xhigh", "medium", "low", "low", "xhigh", "xhigh"]


def test_call_cut_off_by_output_limit_does_not_run() -> None:
    completions = FakeCompletions(
        [
            FakeCall("propose_approaches", APPROACHES),
            CutOff(
                [
                    FakeCall("game_action", '{"action":"move_up","duration":0.5}'),
                    FakeCall("complete_task", "{}", "call-2"),
                ]
            ),
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )
    computer = FakeComputer()

    assert computer_agent(completions, computer).run("move") == "done"
    assert computer.actions == [("game_action", ("move_up", 0.5))]
    assert completions.requests[2]["messages"][-3] == {
        "role": "tool",
        "tool_call_id": "call-2",
        "content": CUT_OFF_CALL,
    }


def test_game_tools_need_no_approach() -> None:
    completions = FakeCompletions(
        [
            [
                FakeCall("api_scan", '{"radius":8}'),
                FakeCall("api_find", FIND, "c2"),
                FakeCall("api_search", '{"query":"gear","kind":"item"}', "c3"),
                FakeCall("api_recipe", '{"item":"iron-gear-wheel"}', "c4"),
                FakeCall("api_craft", '{"recipe":"iron-gear-wheel","count":1}', "c5"),
            ],
            FakeCall("fail_task", '{"reason":"gave up"}'),
        ]
    )
    factorio = FakeFactorio()
    agent = FactorioAgent(
        completions.create,
        None,
        "test-model",
        factorio=factorio,
        control="api",
        report=lambda _: None,
    )

    assert agent.run("craft") == "Failed: gave up"
    assert factorio.actions == [
        ("set_origin", {}),
        ("api_scan", {"radius": 8}),
        ("api_find", json.loads(FIND)),
        ("api_search", {"query": "gear", "kind": "item"}),
        ("api_recipe", {"item": "iron-gear-wheel"}),
        ("api_craft", {"recipe": "iron-gear-wheel", "count": 1}),
    ]


def test_closing_a_task_drops_its_steps() -> None:
    completions = FakeCompletions(
        [
            FakeCall("add_tasks", '{"tasks":[{"title":"walk","done_when":"moved"}]}'),
            FakeCall("propose_approaches", APPROACHES),
            FakeCall("game_action", '{"action":"move_up","duration":0.5}'),
            FakeCall("complete_task", '{"result":"walked north"}'),
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )

    assert computer_agent(completions, FakeComputer()).run("move") == "done"
    last = completions.requests[-2]["messages"]
    called = [
        call["function"]["name"]
        for message in last
        for call in message.get("tool_calls", [])
    ]
    assert called == ["add_tasks"]
    assert "[x] 1. walk -> walked north" in last[-1]["content"]


def test_notes_outlive_closed_tasks() -> None:
    completions = FakeCompletions(
        [
            FakeCall("add_tasks", '{"tasks":[{"title":"walk","done_when":"moved"}]}'),
            FakeCall("notes", '{"text":"drill #7 at 3,4"}'),
            FakeCall("complete_task", '{"result":"walked north"}'),
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )

    assert computer_agent(completions, FakeComputer()).run("move") == "done"
    tasks = completions.requests[-2]["messages"][-1]["content"]
    assert tasks.endswith("Notes:\ndrill #7 at 3,4\n</tasks>")


def test_chain_stops_at_first_error() -> None:
    completions = FakeCompletions(
        [
            [
                FakeCall("game_action", '{"action":'),
                FakeCall("wait", '{"seconds":1}', "call-2"),
            ],
            FakeCall("fail_task", '{"reason":"gave up"}'),
        ]
    )
    computer = FakeComputer()

    assert computer_agent(completions, computer).run("move") == "Failed: gave up"
    assert computer.actions == []
    assert completions.requests[1]["messages"][-3] == {
        "role": "tool",
        "tool_call_id": "call-2",
        "content": "skipped: the chain stopped at an earlier call",
    }


def test_closing_a_task_ends_the_chain() -> None:
    completions = FakeCompletions(
        [
            FakeCall("add_tasks", '{"tasks":[{"title":"walk","done_when":"moved"}]}'),
            [
                FakeCall("propose_approaches", APPROACHES),
                FakeCall(
                    "game_action", '{"action":"move_up","duration":0.5}', "call-2"
                ),
                FakeCall("complete_task", '{"result":"walked north"}', "call-3"),
                FakeCall("wait", '{"seconds":1}', "call-4"),
            ],
            FakeCall("complete_task", '{"result":"done"}'),
        ]
    )
    computer = FakeComputer()
    reports: list[str] = []
    agent = FactorioAgent(
        completions.create, computer, "test-model", report=reports.append
    )

    assert agent.run("move") == "done"
    assert computer.actions == [("game_action", ("move_up", 0.5))]
    assert "step 2: skipped wait" in reports


class FakeObservation:
    def __init__(self, **fields: Any) -> None:
        self.fields = fields

    def __enter__(self) -> FakeObservation:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def update(self, **fields: Any) -> None:
        self.fields.update(fields)


class FakeLangfuse:
    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []

    def start_as_current_observation(self, **fields: Any) -> FakeObservation:
        self.observations.append(FakeObservation(**fields))
        return self.observations[-1]

    def named(self, name: str) -> list[dict[str, Any]]:
        return [o.fields for o in self.observations if o.fields["name"] == name]


MOVE = '{"action":"move_up","duration":0.5}'
REPORT = {
    "category": "tool_bug",
    "tool": "game_action",
    "summary": "moved the wrong way",
    "expected": "north",
    "observed": "south",
    "impact": "worked_around",
}
FEEDBACK = json.dumps(REPORT)


def test_feedback_is_traced_without_breaking_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    langfuse = FakeLangfuse()
    monkeypatch.setattr("auto_factory.harness.agent.get_client", lambda: langfuse)
    completions = FakeCompletions(
        [
            [
                FakeCall("feedback", FEEDBACK),
                FakeCall("propose_approaches", APPROACHES, "call-2"),
                FakeCall("game_action", MOVE, "call-3"),
            ],
            [
                FakeCall("feedback", FEEDBACK),
                FakeCall("complete_task", '{"result":"done"}', "call-2"),
            ],
        ]
    )
    computer = FakeComputer()

    assert computer_agent(completions, computer).run("move") == "done"
    assert computer.actions == [("game_action", ("move_up", 0.5))]
    assert {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "ok; recorded, 9 reports left this run",
    } in completions.requests[1]["messages"]
    feedback = langfuse.named("feedback")
    assert [span["level"] for span in feedback] == ["WARNING", "WARNING"]
    assert feedback[0]["metadata"] == {"previous_call": None}
    assert feedback[1]["metadata"] == {
        "previous_call": {
            "tool": "game_action",
            "arguments": json.loads(MOVE),
            "result": "ok",
        }
    }


def test_feedback_stops_recording_at_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    langfuse = FakeLangfuse()
    monkeypatch.setattr("auto_factory.harness.agent.get_client", lambda: langfuse)
    reports = [FakeCall("feedback", FEEDBACK, f"call-{i}") for i in range(11)]
    completions = FakeCompletions(
        [[*reports, FakeCall("fail_task", '{"reason":"gave up"}', "call-11")]]
    )

    assert computer_agent(completions, FakeComputer()).run("move") == "Failed: gave up"
    feedback = langfuse.named("feedback")
    assert [span.get("level") for span in feedback] == [*["WARNING"] * 10, None]
    assert feedback[-1]["output"] == "not recorded: this run's 10 reports are used up"
    # A full cap leaves nothing for the look back to ask.
    assert len(completions.requests) == 1


def test_look_back_asks_for_unreported_feedback() -> None:
    completions = FakeCompletions(
        [
            [
                FakeCall("feedback", FEEDBACK),
                FakeCall("fail_task", '{"reason":"gave up"}', "call-2"),
            ],
            FakeCall("feedback", json.dumps(REPORT | {"category": "friction"})),
        ]
    )
    reports: list[str] = []
    agent = FactorioAgent(
        completions.create, FakeComputer(), "test-model", report=reports.append
    )

    assert agent.run("move") == "Failed: gave up"
    look_back = completions.requests[1]
    assert look_back["tool_choice"] == "auto"
    [tool] = look_back["tools"]
    assert tool["function"]["name"] == "feedback"
    named = tool["function"]["parameters"]["properties"]["tool"]["enum"]
    assert {"game_action", "complete_task"} <= set(named)
    assert "feedback" not in named
    messages = look_back["messages"]
    assert messages[-1]["content"] == (
        "The run is over: Failed: gave up\nLook back over the whole run and report "
        "with feedback each problem with your tools, observations, instructions, or "
        "harness that you have not reported yet, up to 9 more. If there is none, "
        "reply without a tool call. Already reported:\n- moved the wrong way"
    )
    assert messages[-2]["content"].startswith("<tasks>\nGoal: move\n")
    assert messages[-3]["tool_call_id"] == "call-2"
    assert reports[-1].startswith("look back: feedback {'category': 'friction'")


def test_fell_short_flags_blocked_walks_and_partial_lines() -> None:
    assert fell_short("api_walk_to", '{"reason":"blocked"}')
    assert not fell_short("api_walk_to", '{"reason":"arrived"}')
    assert fell_short("api_place", '{"count":2,"stopped":"out of build reach"}')
    assert fell_short("api_connect", '{"count":1,"stopped":"only 1 of the 2 spots"}')
    assert not fell_short("drag_build", '{"placed":{"transport-belt":5}}')
    assert not fell_short("api_mine", '{"reason":"target gone"}')


def test_trim_tasks_keeps_latest() -> None:
    first = TaskTree("goal")
    messages = [tasks_observation(first), tasks_observation(TaskTree("goal 2"))]

    trim_tasks(messages)

    assert messages[0]["content"] == "<tasks>\n[superseded by later tasks]\n</tasks>"
    assert messages[1]["content"].startswith("<tasks>\nGoal: goal 2\n")


def test_observation_embeds_png() -> None:
    message = observation(Screenshot(b"png", 1, 1))

    assert message["content"][1]["image_url"]["url"].endswith("cG5n")


def test_api_agent_uses_state_without_screenshot() -> None:
    completions = FakeCompletions(
        [
            FakeCall("propose_approaches", APPROACHES),
            FakeCall("api_craft", '{"recipe":"iron-gear-wheel","count":1}'),
            FakeCall("complete_task", '{"result":"crafted"}'),
        ]
    )
    factorio = FakeFactorio()
    agent = FactorioAgent(
        completions.create,
        None,
        "test-model",
        factorio=factorio,
        control="api",
        report=lambda _: None,
    )

    assert agent.run("craft") == "crafted"
    assert factorio.actions == [
        ("set_origin", {}),
        ("api_craft", {"recipe": "iron-gear-wheel", "count": 1}),
    ]
    tools = completions.requests[0]["tools"]
    assert {tool["function"]["name"] for tool in tools} >= {"api_craft", "add_tasks"}
    assert "game_action" not in {tool["function"]["name"] for tool in tools}


def test_screen_only_mixed_agent_watches_and_acts_through_api() -> None:
    completions = FakeCompletions(
        [
            FakeCall("propose_approaches", APPROACHES),
            FakeCall("complete_task", '{"result":"seen"}'),
        ]
    )
    agent = FactorioAgent(
        completions.create,
        None,
        "test-model",
        factorio=FakeFactorio(),
        control="mixed",
        report=lambda _: None,
        screen=FakeComputer(),
    )

    assert agent.run("look") == "seen"
    request = completions.requests[0]
    names = {tool["function"]["name"] for tool in request["tools"]}
    assert "api_craft" in names
    assert names.isdisjoint({"game_action", "drag_build"})
    assert "API tools to act" in request["messages"][0]["content"]
    screenshots = [
        message["content"]
        for message in request["messages"]
        if isinstance(message["content"], list)
    ]
    assert screenshots[0][0]["text"] == (
        "<observation>\nThe game view spans dx -29.8 to 30.2 and dy -17.4 to 16.6.\n"
    )


DRAG_PLAN = {
    "start": {"dx": 1.5, "dy": 0.25},
    "finish": {"dx": 5.5, "dy": 0.25},
    "tiles": 5,
    "zoom": 1,
    "resolution": {"width": 1920, "height": 1080},
}
DRAG_ARGUMENTS = {"item": "transport-belt", "dx": 1, "dy": 0, "direction": "east"}


def test_mixed_agent_drags_between_tile_centres() -> None:
    arguments = DRAG_ARGUMENTS | {"count": 8}
    completions = FakeCompletions(
        [
            FakeCall("propose_approaches", APPROACHES),
            FakeCall("drag_build", json.dumps(arguments)),
            FakeCall("complete_task", '{"result":"built"}'),
        ]
    )
    computer = FakeComputer()
    factorio = FakeFactorio(
        {"drag_prepare": DRAG_PLAN, "drag_finish": {"placed": {"transport-belt": 5}}}
    )
    agent = FactorioAgent(
        completions.create,
        computer,
        "test-model",
        factorio=factorio,
        control="mixed",
        report=lambda _: None,
    )

    assert agent.run("build") == "built"
    assert computer.actions == [
        ("wait", (0.25,)),
        ("drag", (525, 507, 592, 507, "left", 0.25)),
        ("wait", (0.25,)),
    ]
    assert [action for action in factorio.actions if action[0] != "camera"] == [
        ("set_origin", {}),
        ("drag_prepare", arguments),
        ("drag_finish", {}),
    ]
    assert {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"placed":{"transport-belt":5}}',
    } in completions.requests[2]["messages"]


def test_drag_build_finishes_after_resolution_mismatch() -> None:
    computer = FakeComputer()
    plan = DRAG_PLAN | {"resolution": {"width": 1280, "height": 720}}
    factorio = FakeFactorio({"drag_prepare": plan, "drag_finish": {}})

    with pytest.raises(RuntimeError, match="run it fullscreen"):
        execute_tool(computer, factorio, "drag_build", DRAG_ARGUMENTS | {"count": 1})
    assert computer.actions == []
    assert [method for method, _ in factorio.actions] == [
        "drag_prepare",
        "drag_finish",
    ]


def test_drag_build_needs_desktop_and_api() -> None:
    def names(desktop: bool, api: bool) -> set[str]:
        return {tool["function"]["name"] for tool in tools_for(desktop, api)}

    assert "drag_build" in names(desktop=True, api=True)
    assert "drag_build" not in names(True, False) | names(False, True)


def test_thinking_uses_chatml_parts() -> None:
    message = SimpleNamespace(reasoning="look first")

    assert thinking(message) == {
        "thinking": [{"type": "thinking", "content": "look first"}]
    }
    assert thinking(SimpleNamespace(content="ok")) == {}


def test_usage_details_maps_token_counts() -> None:
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3)

    assert usage_details(SimpleNamespace(usage=usage)) == {"input": 10, "output": 3}
    assert usage_details(SimpleNamespace()) is None


def test_game_state_observation_wraps_json() -> None:
    message = game_state_observation({"tick": 42})

    assert message["content"] == '<game_state>\n{"tick":42}\n</game_state>'


def test_trim_game_states_keeps_latest_three() -> None:
    messages = [game_state_observation({"tick": tick}) for tick in range(5)]

    trim_game_states(messages)

    assert messages[0]["content"] == (
        "<game_state>\n[structured observation evicted]\n</game_state>"
    )
    assert messages[1]["content"] == (
        "<game_state>\n[structured observation evicted]\n</game_state>"
    )
    assert messages[2]["content"] == '<game_state>\n{"tick":2}\n</game_state>'


def test_trim_images_keeps_latest() -> None:
    messages = [
        observation(Screenshot(str(index).encode(), 1, 1)) for index in range(3)
    ]

    trim_images(messages)

    evicted = "<observation>\n[screenshot evicted]\n</observation>"
    assert messages[0]["content"] == evicted
    assert messages[1]["content"] == evicted
    assert messages[2]["content"][1]["type"] == "image_url"
