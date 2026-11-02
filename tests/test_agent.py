from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from auto_factory.control.computer import Screenshot
from auto_factory.harness.agent import (
    FactorioAgent,
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


class FakeCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.id = "call-1"
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


class FakeCompletions:
    def __init__(self, calls: list[FakeCall]) -> None:
        self.calls = calls
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        # The agent keeps mutating its message list after each request.
        self.requests.append(deepcopy(kwargs))
        call = self.calls.pop(0)
        message = SimpleNamespace(content=None, tool_calls=[call])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


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


class FakeFactorio:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict[str, object]]] = []

    def observe(self, radius: float) -> dict[str, object]:
        return {"radius": radius, "player": {"world_position": {"x": 1, "y": 2}}}

    def execute(self, name: str, arguments: dict[str, object]) -> str:
        self.actions.append((name, arguments))
        return '{"queued":1}'


APPROACHES = '{"approaches":["a","b"],"reason":"a is best"}'


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
    assert len(completions.requests) == 3


def test_game_tools_need_an_approach() -> None:
    completions = FakeCompletions(
        [
            FakeCall("game_action", '{"action":"move_up","duration":0.5}'),
            FakeCall("fail_task", '{"reason":"gave up"}'),
        ]
    )
    computer = FakeComputer()

    assert computer_agent(completions, computer).run("move") == "Failed: gave up"
    assert computer.actions == []
    assert completions.requests[1]["messages"][-3]["content"].startswith(
        "error: the goal has no approach yet"
    )


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
    last = completions.requests[-1]["messages"]
    called = [
        call["function"]["name"]
        for message in last
        for call in message.get("tool_calls", [])
    ]
    assert called == ["add_tasks"]
    assert "[x] 1. walk -> walked north" in last[-1]["content"]


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
        ("api_craft", {"recipe": "iron-gear-wheel", "count": 1})
    ]
    tools = completions.requests[0]["tools"]
    assert {tool["function"]["name"] for tool in tools} >= {"api_craft", "add_tasks"}
    assert "game_action" not in {tool["function"]["name"] for tool in tools}


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


def test_trim_images_keeps_latest_three() -> None:
    messages = [
        observation(Screenshot(str(index).encode(), 1, 1)) for index in range(5)
    ]

    trim_images(messages)

    assert messages[0]["content"][1] == {
        "type": "text",
        "text": "[screenshot evicted]",
    }
    assert messages[1]["content"][1] == {
        "type": "text",
        "text": "[screenshot evicted]",
    }
    assert messages[2]["content"][1]["type"] == "image_url"
