local RESPONSE_PREFIX = "__AUTO_FACTORY__"

local DIRECTIONS = {
  north = defines.direction.north,
  east = defines.direction.east,
  south = defines.direction.south,
  west = defines.direction.west,
}

local OBSERVABLE_TYPES = {
  "accumulator",
  "ammo-turret",
  "assembling-machine",
  "beacon",
  "boiler",
  "burner-generator",
  "car",
  "cargo-wagon",
  "container",
  "electric-pole",
  "furnace",
  "generator",
  "inserter",
  "item-entity",
  "lab",
  "lamp",
  "loader",
  "locomotive",
  "logistic-container",
  "mining-drill",
  "offshore-pump",
  "pipe",
  "pipe-to-ground",
  "pump",
  "radar",
  "reactor",
  "roboport",
  "rocket-silo",
  "simple-entity",
  "solar-panel",
  "splitter",
  "storage-tank",
  "train-stop",
  "transport-belt",
  "tree",
  "turret",
  "underground-belt",
}

local function ensure_storage()
  storage.actions = storage.actions or {}
end

script.on_init(ensure_storage)
script.on_configuration_changed(ensure_storage)

local function fail(message)
  error(message, 0)
end

local function required_number(params, name)
  local value = tonumber(params[name])
  if value == nil then
    fail(name .. " must be a number")
  end
  return value
end

local function required_string(params, name)
  local value = params[name]
  if type(value) ~= "string" or value == "" then
    fail(name .. " must be a non-empty string")
  end
  return value
end

local function get_player(params)
  local player = nil
  if params.player_index then
    player = game.get_player(params.player_index)
  elseif params.player_name then
    player = game.get_player(params.player_name)
  elseif #game.connected_players > 0 then
    player = game.connected_players[1]
  elseif #game.players > 0 then
    player = game.players[1]
  end
  if not player or not player.valid then
    fail("no Factorio player is available")
  end
  if not player.character then
    fail("the selected player has no character")
  end
  return player
end

local function position_from(params)
  return {x = required_number(params, "x"), y = required_number(params, "y")}
end

local function direction_from(params)
  local name = required_string(params, "direction")
  local direction = DIRECTIONS[name]
  if not direction then
    fail("direction must be north, east, south, or west")
  end
  return direction
end

local function distance_squared(first, second)
  local dx = first.x - second.x
  local dy = first.y - second.y
  return dx * dx + dy * dy
end

local function rounded(value)
  return math.floor(value * 100 + 0.5) / 100
end

local function plain_position(position)
  return {x = rounded(position.x), y = rounded(position.y)}
end

local function inventory_contents(inventory)
  local result = {}
  if not inventory or not inventory.valid then
    return result
  end
  for _, stack in pairs(inventory.get_contents()) do
    result[stack.name] = (result[stack.name] or 0) + stack.count
  end
  return result
end

local function entity_contents(entity)
  local result = {}
  local maximum = entity.get_max_inventory_index()
  for index = 1, maximum do
    local inventory = entity.get_inventory(index)
    if inventory and inventory.valid then
      for name, count in pairs(inventory_contents(inventory)) do
        result[name] = (result[name] or 0) + count
      end
    end
  end
  return result
end

local function find_entity(player, name, position)
  local candidates = player.surface.find_entities_filtered {
    position = position,
    radius = 0.8,
    name = name,
    limit = 10,
  }
  local closest = nil
  local closest_distance = nil
  for _, entity in pairs(candidates) do
    local distance = distance_squared(position, entity.position)
    if closest_distance == nil or distance < closest_distance then
      closest = entity
      closest_distance = distance
    end
  end
  if not closest then
    fail("no " .. name .. " found near the requested position")
  end
  return closest
end

local function stop_player(player)
  player.walking_state = {walking = false, direction = defines.direction.north}
  player.mining_state = {mining = false}
  storage.actions[player.index] = nil
end

script.on_event(defines.events.on_tick, function(event)
  ensure_storage()
  for player_index, action in pairs(storage.actions) do
    local player = game.get_player(player_index)
    if not player or not player.valid or not player.character then
      storage.actions[player_index] = nil
    elseif event.tick >= action.until_tick then
      stop_player(player)
    elseif action.kind == "walk" then
      player.walking_state = {walking = true, direction = action.direction}
    elseif action.kind == "mine" then
      player.update_selected_entity(action.position)
      local target = player.selected
      if target and target.valid and player.can_reach_entity(target) then
        player.mining_state = {mining = true, position = action.position}
      else
        stop_player(player)
      end
    end
  end
end)

local handlers = {}

function handlers.observe(params)
  local player = get_player(params)
  local radius = math.max(2, math.min(64, tonumber(params.radius) or 12))
  local resources = {}
  local resource_entities = player.surface.find_entities_filtered {
    position = player.position,
    radius = radius,
    type = "resource",
    limit = 1000,
  }
  for _, entity in pairs(resource_entities) do
    local summary = resources[entity.name]
    local distance = distance_squared(player.position, entity.position)
    if not summary then
      summary = {count = 0, amount = 0, nearest = nil, nearest_distance = nil}
      resources[entity.name] = summary
    end
    summary.count = summary.count + 1
    summary.amount = summary.amount + entity.amount
    if summary.nearest_distance == nil or distance < summary.nearest_distance then
      summary.nearest = plain_position(entity.position)
      summary.nearest_distance = distance
    end
  end
  for _, summary in pairs(resources) do
    summary.nearest_distance = nil
  end

  local entities = {}
  local nearby = player.surface.find_entities_filtered {
    position = player.position,
    radius = radius,
    type = OBSERVABLE_TYPES,
    limit = 100,
  }
  for _, entity in pairs(nearby) do
    local entry = {
      name = entity.name,
      type = entity.type,
      position = plain_position(entity.position),
      direction = entity.direction,
    }
    if entity.health then
      entry.health = rounded(entity.health)
    end
    local contents = entity_contents(entity)
    if next(contents) then
      entry.items = contents
    end
    local recipe_ok, recipe = pcall(entity.get_recipe)
    if recipe_ok and recipe then
      entry.recipe = recipe.name
    end
    local status_ok, status = pcall(function() return entity.status end)
    if status_ok and status then
      entry.status = status
    end
    table.insert(entities, entry)
  end

  local action = storage.actions[player.index]
  local action_state = nil
  if action then
    action_state = {
      kind = action.kind,
      ticks_remaining = math.max(0, action.until_tick - game.tick),
    }
  end
  return {
    tick = game.tick,
    speed = game.speed,
    player = {
      index = player.index,
      name = player.name,
      position = plain_position(player.position),
      health = player.character.health,
      inventory = inventory_contents(player.get_main_inventory()),
      crafting_queue_size = player.crafting_queue_size,
      crafting_progress = rounded(player.crafting_queue_progress),
      action = action_state,
    },
    radius = radius,
    resources = resources,
    entities = entities,
  }
end

function handlers.walk(params)
  local player = get_player(params)
  local direction = direction_from(params)
  local seconds = math.max(0.1, math.min(10, required_number(params, "seconds")))
  stop_player(player)
  storage.actions[player.index] = {
    kind = "walk",
    direction = direction,
    until_tick = game.tick + math.ceil(seconds * 60),
  }
  return {scheduled = "walk", seconds = seconds}
end

function handlers.mine(params)
  local player = get_player(params)
  local position = position_from(params)
  local seconds = math.max(0.1, math.min(10, required_number(params, "seconds")))
  player.update_selected_entity(position)
  local target = player.selected
  if not target or not target.valid then
    fail("no mineable entity is selected at that position")
  end
  if not player.can_reach_entity(target) then
    fail("the target is outside mining reach")
  end
  stop_player(player)
  storage.actions[player.index] = {
    kind = "mine",
    position = position,
    until_tick = game.tick + math.ceil(seconds * 60),
  }
  return {scheduled = "mine", target = target.name, seconds = seconds}
end

function handlers.stop(params)
  local player = get_player(params)
  stop_player(player)
  return {stopped = true}
end

function handlers.craft(params)
  local player = get_player(params)
  local recipe = required_string(params, "recipe")
  local count = math.max(1, math.min(100, math.floor(required_number(params, "count"))))
  local queued = player.begin_crafting {recipe = recipe, count = count, silent = false}
  return {recipe = recipe, requested = count, queued = queued}
end

local function restore_cursor(player)
  local cursor = player.cursor_stack
  if cursor and cursor.valid_for_read then
    local stack = {name = cursor.name, count = cursor.count}
    if cursor.quality then
      stack.quality = cursor.quality.name
    end
    player.get_main_inventory().insert(stack)
    cursor.clear()
  end
end

function handlers.place(params)
  local player = get_player(params)
  local item = required_string(params, "item")
  local position = position_from(params)
  local direction = direction_from(params)
  if distance_squared(player.position, position) > player.build_distance ^ 2 then
    fail("the position is outside build reach")
  end
  local cursor = player.cursor_stack
  if not cursor or cursor.valid_for_read then
    fail("the player cursor must be empty before API placement")
  end
  local source = player.get_main_inventory().find_item_stack(item)
  if not source then
    fail("the player has no " .. item)
  end
  if not cursor.transfer_stack(source, 1) then
    fail("could not move " .. item .. " into the cursor")
  end
  if not player.can_build_from_cursor {position = position, direction = direction} then
    restore_cursor(player)
    fail("the item cannot be built at that position")
  end
  local before = cursor.count
  player.build_from_cursor {position = position, direction = direction}
  local remaining = cursor.valid_for_read and cursor.count or 0
  restore_cursor(player)
  if remaining >= before then
    fail("Factorio did not place the item")
  end
  return {placed = item, position = plain_position(position), direction = params.direction}
end

function handlers.insert(params)
  local player = get_player(params)
  local name = required_string(params, "entity")
  local item = required_string(params, "item")
  local count = math.max(1, math.floor(required_number(params, "count")))
  local entity = find_entity(player, name, position_from(params))
  if not player.can_reach_entity(entity) then
    fail("the entity is outside reach")
  end
  local inventory = player.get_main_inventory()
  local removed = inventory.remove {name = item, count = count}
  local inserted = entity.insert {name = item, count = removed}
  if inserted < removed then
    inventory.insert {name = item, count = removed - inserted}
  end
  return {entity = name, item = item, requested = count, inserted = inserted}
end

function handlers.take(params)
  local player = get_player(params)
  local name = required_string(params, "entity")
  local item = required_string(params, "item")
  local count = math.max(1, math.floor(required_number(params, "count")))
  local entity = find_entity(player, name, position_from(params))
  if not player.can_reach_entity(entity) then
    fail("the entity is outside reach")
  end
  local removed = entity.remove_item {name = item, count = count}
  local inserted = player.get_main_inventory().insert {name = item, count = removed}
  if inserted < removed then
    entity.insert {name = item, count = removed - inserted}
  end
  return {entity = name, item = item, requested = count, taken = inserted}
end

commands.add_command("af", "Call the auto-factory JSON API", function(command)
  ensure_storage()
  local request = helpers.json_to_table(command.parameter or "")
  if type(request) ~= "table" then
    rcon.print(RESPONSE_PREFIX .. helpers.table_to_json {
      id = nil,
      ok = false,
      error = "request must be a JSON object",
    })
    return
  end
  local handler = handlers[request.method]
  if not handler then
    rcon.print(RESPONSE_PREFIX .. helpers.table_to_json {
      id = request.id,
      ok = false,
      error = "unknown method: " .. tostring(request.method),
    })
    return
  end
  local ok, result = pcall(handler, request.params or {})
  local response = {id = request.id, ok = ok}
  if ok then
    response.result = result
  else
    response.error = tostring(result)
  end
  rcon.print(RESPONSE_PREFIX .. helpers.table_to_json(response))
end)
