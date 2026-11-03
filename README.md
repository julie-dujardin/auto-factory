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

This links the mod from this checkout and enables RCON with the `.env` credentials. For `api` and `mixed` control, host a multiplayer game, then check the connection with `uv run --env-file .env auto-factory --check-api`.

On macOS there is no isolated display, so only `--control api` works.

Set your objective:
```bash
uv run --env-file .env auto-factory --control mixed "launch 10 rockets per minute"
```
