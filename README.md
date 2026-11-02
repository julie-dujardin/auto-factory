# Auto Factory

Factorio agent

## Setup

```bash
uv sync
cp .env.example .env
```

fill in env vars

## Run

Start Factorio:

```bash
uv run auto-factory-game
```

Set your objective:
```bash
uv run auto-factory --control mixed "launch 10 rockets per minute"
```
