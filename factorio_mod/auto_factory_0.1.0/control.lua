local actions = require("scripts.actions")
local ids = require("scripts.ids")
local info = require("scripts.info")
local interact = require("scripts.interact")
local observe = require("scripts.observe")
local recipes = require("scripts.recipes")
local research = require("scripts.research")
local resources = require("scripts.resources")

local RESPONSE_PREFIX = "__AUTO_FACTORY__"

local handlers = {}
for _, module in pairs {actions, ids, info, interact, observe, recipes, research, resources} do
  for name, handler in pairs(module.handlers) do
    assert(not handlers[name], "duplicate API method " .. name)
    handlers[name] = handler
  end
end

-- Night darkens screenshots without adding anything the agent should plan around.
-- A frozen noon is used because always_day leaves 2.1 dark.
local function make_day(surface)
  surface.daytime = 0
  surface.freeze_daytime = true
end

local function ensure_world()
  actions.ensure_storage()
  for _, surface in pairs(game.surfaces) do
    make_day(surface)
  end
end

script.on_init(ensure_world)
script.on_configuration_changed(ensure_world)
script.on_event(defines.events.on_surface_created, function(event)
  make_day(game.surfaces[event.surface_index])
end)
script.on_event(defines.events.on_tick, actions.on_tick)
script.on_event(defines.events.on_player_mined_item, actions.on_player_mined_item)
script.on_event(
  defines.events.on_script_path_request_finished,
  actions.on_script_path_request_finished
)

local function respond(response)
  rcon.print(RESPONSE_PREFIX .. helpers.table_to_json(response))
end

commands.add_command("af", "Call the auto-factory JSON API", function(command)
  ensure_world()
  local request = helpers.json_to_table(command.parameter or "")
  if type(request) ~= "table" then
    respond {id = nil, ok = false, error = "request must be a JSON object"}
    return
  end
  local handler = handlers[request.method]
  if not handler then
    respond {
      id = request.id,
      ok = false,
      error = "unknown method: " .. tostring(request.method),
    }
    return
  end
  local ok, result = pcall(handler, request.params or {})
  local response = {id = request.id, ok = ok}
  if ok then
    response.result = result
  else
    response.error = tostring(result)
  end
  respond(response)
end)
