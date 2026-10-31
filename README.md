# auto-factory

A small agent loop for letting an OpenAI-compatible vision model play Factorio
through computer use, a structured game API, or both.

## Setup

Install the project and configure H Company's Holo model:

```shell
uv sync
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.hcompany.ai/v1/"
export MODEL_NAME="holo3-1-35b-a3b"
```

The harness uses the standard OpenAI client environment variables, so another
OpenAI-compatible vision model only needs different values:

```shell
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://provider.example/v1"
export MODEL_NAME="vision-model"
```

## Computer control

Computer control runs Factorio in a visible, private Xwayland window. Screenshots
and input stay inside that window, leaving the normal desktop available.

Start Factorio:

```shell
uv run auto-factory-game
```

Then start the agent in another terminal:

```shell
uv run auto-factory "Start a new freeplay game and gather wood and iron"
```

The launcher discovers Flatpak Steam and native Steam installations. Set
`FACTORIO_BIN` if Factorio is elsewhere. It uses display `:99` at `1920x1080`;
`AUTO_FACTORY_DISPLAY` and `AUTO_FACTORY_SIZE` override those defaults.

## Factorio API

API and mixed control use the bundled `auto_factory` mod and Factorio's RCON
server. For native Factorio, install the development copy with:

```shell
mkdir -p ~/.factorio/mods
ln -s "$PWD/factorio_mod/auto_factory_0.1.0" ~/.factorio/mods/
```

For Flatpak Steam, copy it into the sandboxed Factorio data directory:

```shell
mkdir -p ~/.var/app/com.valvesoftware.Steam/.factorio/mods
cp -R factorio_mod/auto_factory_0.1.0 \
  ~/.var/app/com.valvesoftware.Steam/.factorio/mods/
```

Enable the mod, then configure graphical Factorio under `[other]` in
`config.ini`:

```ini
local-rcon-socket=127.0.0.1:27015
local-rcon-password=choose-a-password
```

Flatpak Steam stores the file at
`~/.var/app/com.valvesoftware.Steam/.factorio/config/config.ini`. The same
settings are exposed in Factorio by holding `Ctrl+Alt` while opening
**Settings**, then selecting **The rest**.

Keep RCON bound to loopback because it is not encrypted. Restart Factorio and
use **Play → Multiplayer → Host saved game**, then configure the harness:

```shell
export FACTORIO_RCON_PASSWORD="choose-a-password"
uv run auto-factory --check-api
uv run auto-factory --control api "Gather ten iron ore"
```

`FACTORIO_RCON_HOST` and `FACTORIO_RCON_PORT` default to `127.0.0.1` and
`27015`. RCON configuration is environment-only.

API observations include player position, inventory, crafting, nearby
resources, and nearby entities. Actions use normal character reach, collision,
inventory, mining speed, and crafting time.

Factorio RCON options:
https://wiki.factorio.com/Command_line_parameters

Factorio runtime mod API:
https://lua-api.factorio.com/latest/index-runtime.html

## Mixed control

Mixed mode combines screenshots and input with the structured API:

```shell
uv run auto-factory-game
```

```shell
export FACTORIO_RCON_PASSWORD="choose-a-password"
uv run auto-factory --control mixed "Build a burner mining drill on iron"
```

## Controls

The model receives semantic actions for Factorio's default movement, inventory,
pickup, rotation, map, alt-mode, shooting, pause, and quickbar bindings. It can
also move, click, hold, drag, scroll, and type using normalized `[0, 1000]`
screenshot coordinates.

API tools use the absolute world coordinates returned in structured
observations. Run `uv run auto-factory --help` for step and observation limits.
Press `Ctrl-C` to stop the agent.

## Tests

```shell
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Install the uv-managed pre-commit hooks in each clone:

```shell
uv run pre-commit install
```

Run every hook manually with:

```shell
uv run pre-commit run --all-files
```
