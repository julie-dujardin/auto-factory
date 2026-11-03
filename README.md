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
