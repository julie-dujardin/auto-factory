import pytest

from auto_factory.harness import cli
from auto_factory.harness.cli import score_research


class CountingFactorio:
    def __init__(self, researched: int) -> None:
        self.researched = researched

    def observe(self, radius: float) -> dict[str, object]:
        return {"research": {"researched": self.researched}}

    def execute(self, name: str, arguments: dict[str, object]) -> str:
        raise AssertionError("not used")

    def call(self, method: str, params: dict[str, object]) -> object:
        raise AssertionError("not used")


class RecordingEpisode:
    def __init__(self) -> None:
        self.scores: list[dict[str, object]] = []

    def score_trace(self, **score: object) -> None:
        self.scores.append(score)


def test_research_score_is_technologies_gained() -> None:
    episode = RecordingEpisode()

    score_research(episode, CountingFactorio(5), start=2)

    assert episode.scores == [
        {"name": "research_completed", "value": 3, "data_type": "NUMERIC"}
    ]


def test_unreachable_game_skips_score(capsys) -> None:
    class GoneFactorio(CountingFactorio):
        def observe(self, radius: float) -> dict[str, object]:
            raise RuntimeError("RCON request failed")

    episode = RecordingEpisode()

    score_research(episode, GoneFactorio(0), start=0)

    assert episode.scores == []
    assert "Could not score research" in capsys.readouterr().err


def test_macos_rejects_computer_control(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.sys, "argv", ["auto-factory", "--control", "computer", "x"])
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("MODEL_NAME", "model")

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 2
    assert "--control api" in capsys.readouterr().err


def test_macos_mixed_watches_the_window(monkeypatch) -> None:
    class Built(Exception):
        pass

    def build_agent(**kwargs: object) -> None:
        built.update(kwargs)
        raise Built

    built: dict[str, object] = {}
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.sys, "argv", ["auto-factory", "--control", "mixed", "x"])
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("MODEL_NAME", "model")
    monkeypatch.setenv("FACTORIO_RCON_PASSWORD", "secret")
    monkeypatch.setattr(cli, "RconFactorioAPI", lambda *_: CountingFactorio(0))
    monkeypatch.setattr(cli, "WindowScreen", lambda: "window")
    monkeypatch.setattr(cli, "FactorioAgent", build_agent)

    with pytest.raises(Built):
        cli.main()

    assert built["computer"] is None
    assert built["screen"] == "window"


def test_reasoning_effort_defaults_to_medium() -> None:
    assert cli.parser().parse_args(["x"]).reasoning_effort == "medium"
    assert (
        cli.parser().parse_args(["--reasoning-effort", "low", "x"]).reasoning_effort
        == "low"
    )
