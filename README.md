# Auto Factory

Factorio agent

## Setup

```bash
uv sync
cp .env.example .env
```

fill in env vars

Launch Factorio once so it creates its config, then quit.

## Run

Start Factorio:

```bash
uv run --env-file .env auto-factory-game
```

This links the mod from this checkout and enables RCON with the `.env` credentials. For `api` and `mixed` control, start a game, then check the connection with `uv run --env-file .env auto-factory --check-api`.

On macOS there is no isolated display for desktop input, so `--control computer` is unavailable. `--control mixed` acts through the API while the agent watches screenshots of the Factorio window; grant your terminal Screen Recording in System Settings > Privacy & Security.

Set your objective:
```bash
uv run --env-file .env auto-factory --control mixed "launch 10 rockets per minute"
```

### Scenarios

When a run starts from one of your saves, describe that save's world in `scenarios/<name>.md` and pass `--scenario <name>`. The description goes in the prompt before the objective, and the trace is tagged `scenario:<name>`.

```bash
uv run --env-file .env auto-factory --control api --scenario belt-factory "automate transport belts"
```

## Call tools by hand

`auto-factory-tool` sends one API tool call over RCON, exactly as the agent would, and prints the result:

```bash
uv run --env-file .env auto-factory-tool find --name ore --radius 50 --sort distance --limit 5
uv run --env-file .env auto-factory-tool walk_to --dx 10 --dy -4
uv run --env-file .env auto-factory-tool api_place '{"item": "stone-furnace", "dx": 2, "dy": 0, "direction": "north", "count": 1, "line_direction": "east"}'
```

Tools take their short (`find`) or full (`api_find`) name. Arguments come as flags, as a JSON object copied from a trace, or both (flags win); omitted text fields are sent empty. `auto-factory-tool <tool> --help` lists a tool's arguments.
