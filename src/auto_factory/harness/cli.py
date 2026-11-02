from __future__ import annotations

import argparse
import json
import os
import sys

from langfuse import get_client, propagate_attributes
from openai import OpenAI

from ..control.computer import Computer, DesktopComputer
from ..control.factorio import FactorioAPI, RconFactorioAPI
from .agent import FactorioAgent
from .tools import ControlMode


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
        "--check-api",
        action="store_true",
        help="Print one Factorio API observation and exit",
    )
    return result


def rcon_from_environment() -> RconFactorioAPI:
    password = os.environ.get("FACTORIO_RCON_PASSWORD")
    if not password:
        raise SystemExit("Set FACTORIO_RCON_PASSWORD for API control.")
    try:
        port = int(os.environ.get("FACTORIO_RCON_PORT", "27015"))
    except ValueError as exc:
        raise SystemExit("FACTORIO_RCON_PORT must be an integer.") from exc
    return RconFactorioAPI(
        host=os.environ.get("FACTORIO_RCON_HOST", "127.0.0.1"),
        port=port,
        password=password,
    )


def main() -> None:
    args = parser().parse_args()
    if not 2 <= args.observation_radius <= 64:
        print("--observation-radius must be between 2 and 64.", file=sys.stderr)
        raise SystemExit(2)

    needs_rcon = args.control in {"api", "mixed"} or args.check_api
    factorio: FactorioAPI | None = rcon_from_environment() if needs_rcon else None
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

    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY.", file=sys.stderr)
        raise SystemExit(2)
    model = os.environ.get("MODEL_NAME")
    if not model:
        print("Set MODEL_NAME.", file=sys.stderr)
        raise SystemExit(2)

    control: ControlMode = args.control
    computer: Computer | None = None
    if control in {"computer", "mixed"}:
        display = os.environ.get("AUTO_FACTORY_DISPLAY", ":99")
        computer = DesktopComputer(display)

    client = OpenAI()
    agent = FactorioAgent(
        create_completion=client.chat.completions.create,
        computer=computer,
        model=model,
        factorio=factorio,
        control=control,
        observation_radius=args.observation_radius,
        max_steps=args.max_steps,
    )

    print(f"Starting {control} control. Press Ctrl-C to stop.", flush=True)
    langfuse = get_client()
    with (
        langfuse.start_as_current_observation(
            as_type="agent", name="episode", input=args.task
        ) as episode,
        propagate_attributes(trace_name="episode", tags=[control, model]),
    ):
        if url := langfuse.get_trace_url():
            print(f"Trace: {url}", flush=True)
        try:
            answer = agent.run(args.task)
        except KeyboardInterrupt:
            episode.update(level="WARNING", status_message="stopped by user")
            print("\nStopped.", file=sys.stderr)
            raise SystemExit(130) from None
        episode.update(output=answer)
        print(answer)
