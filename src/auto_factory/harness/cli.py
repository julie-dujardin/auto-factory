from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from langfuse import get_client, propagate_attributes
from openai import OpenAI

from ..control.computer import Computer, DesktopComputer, Screen, WindowScreen
from ..control.factorio import FactorioAPI, RconFactorioAPI, rcon_environment
from .agent import REASONING_EFFORTS, FactorioAgent
from .tools import ControlMode

SCENARIOS = Path(__file__).resolve().parents[3] / "scenarios"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Let an OpenAI-compatible model play Factorio.",
    )
    result.add_argument("task", nargs="?", help="The objective for the agent")
    result.add_argument(
        "--control",
        choices=["computer", "api", "mixed"],
        default="computer",
        help="Observation and action surface",
    )
    result.add_argument(
        "--observation-radius",
        type=float,
        default=12,
        help="World radius included in API observations",
    )
    result.add_argument("--max-steps", type=int, default=100)
    result.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        default="medium",
        help="Thinking per turn; a turn cut off while thinking retries one lower",
    )
    result.add_argument(
        "--scenario",
        help=f"Name of the save's description in {SCENARIOS}, without .md",
    )
    result.add_argument(
        "--check-api",
        action="store_true",
        help="Print one Factorio API observation and exit",
    )
    return result


def scenario_description(name: str) -> str:
    available = sorted(path.stem for path in SCENARIOS.glob("*.md"))
    if name not in available:
        raise ValueError(
            f"unknown scenario {name!r}; available: {', '.join(available) or 'none'}"
        )
    return (SCENARIOS / f"{name}.md").read_text().strip()


def researched_count(factorio: FactorioAPI) -> int:
    return int(factorio.observe(2)["research"]["researched"])


def score_research(episode: Any, factorio: FactorioAPI, start: int) -> None:
    try:
        completed = researched_count(factorio) - start
    except (RuntimeError, ValueError) as exc:
        print(f"Could not score research: {exc}", file=sys.stderr)
        return
    episode.score_trace(name="research_completed", value=completed, data_type="NUMERIC")


def main() -> None:
    args = parser().parse_args()
    if not 2 <= args.observation_radius <= 64:
        print("--observation-radius must be between 2 and 64.", file=sys.stderr)
        raise SystemExit(2)

    needs_rcon = args.control in {"api", "mixed"} or args.check_api
    factorio: FactorioAPI | None = (
        RconFactorioAPI(*rcon_environment()) if needs_rcon else None
    )
    if args.check_api:
        assert factorio is not None
        print(json.dumps(factorio.observe(args.observation_radius), indent=2))
        return

    if not args.task:
        print("A task is required unless --check-api is used.", file=sys.stderr)
        raise SystemExit(2)
    if args.max_steps < 1:
        print("--max-steps must be positive.", file=sys.stderr)
        raise SystemExit(2)
    scenario: str | None = None
    if args.scenario is not None:
        try:
            scenario = scenario_description(args.scenario)
        except ValueError as exc:
            print(f"--scenario: {exc}", file=sys.stderr)
            raise SystemExit(2) from None

    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY.", file=sys.stderr)
        raise SystemExit(2)
    model = os.environ.get("MODEL_NAME")
    if not model:
        print("Set MODEL_NAME.", file=sys.stderr)
        raise SystemExit(2)

    control: ControlMode = args.control
    computer: Computer | None = None
    screen: Screen | None = None
    if control in {"computer", "mixed"}:
        if sys.platform != "darwin":
            display = os.environ.get("AUTO_FACTORY_DISPLAY", ":99")
            computer = DesktopComputer(display)
        elif control == "mixed":
            screen = WindowScreen()
        else:
            print(
                "Desktop input needs an isolated display, which macOS lacks; use "
                "--control mixed to act through the API while watching the window, "
                "or --control api.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    client = OpenAI()
    agent = FactorioAgent(
        create_completion=client.chat.completions.create,
        computer=computer,
        model=model,
        factorio=factorio,
        control=control,
        observation_radius=args.observation_radius,
        max_steps=args.max_steps,
        reasoning_effort=args.reasoning_effort,
        screen=screen,
    )

    print(f"Starting {control} control. Press Ctrl-C to stop.", flush=True)
    langfuse = get_client()
    with (
        langfuse.start_as_current_observation(
            as_type="agent", name="episode", input=args.task
        ) as episode,
        propagate_attributes(
            trace_name="episode",
            tags=[control, model]
            + ([f"scenario:{args.scenario}"] if args.scenario else []),
            metadata={"scenario": args.scenario} if args.scenario else None,
        ),
    ):
        if url := langfuse.get_trace_url():
            print(f"Trace: {url}", flush=True)
        research_start = researched_count(factorio) if factorio else None
        try:
            answer = agent.run(args.task, scenario)
        except KeyboardInterrupt:
            episode.update(level="WARNING", status_message="stopped by user")
            print("\nStopped.", file=sys.stderr)
            raise SystemExit(130) from None
        finally:
            if factorio and research_start is not None:
                score_research(episode, factorio, research_start)
        episode.update(output=answer)
        print(answer)
