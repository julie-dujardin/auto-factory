# Auto Factory

Factorio agent

## Setup

```bash
uv sync
cp .env.example .env
```

fill in env vars

### macOS

Only `--control api` works: there is no isolated display, so `auto-factory-game` runs Factorio on the main screen.

1. Install Factorio through Steam, launch it once, and quit.
2. Link the mod:
   ```bash
   ln -s "$PWD/factorio_mod/auto_factory_0.1.0" ~/Library/Application\ Support/factorio/mods/
   ```
3. Under `[other]` in `~/Library/Application Support/factorio/config/config.ini`, set the RCON values from `.env`:
   ```ini
   local-rcon-socket=127.0.0.1:27015
   local-rcon-password=0451
   ```
4. Run `uv run auto-factory-game`, then host a new multiplayer game.
5. Check the connection with `uv run auto-factory --check-api`.

## Run

Start Factorio:

```bash
uv run auto-factory-game
```

Set your objective:
```bash
uv run auto-factory --control mixed "launch 10 rockets per minute"
```
