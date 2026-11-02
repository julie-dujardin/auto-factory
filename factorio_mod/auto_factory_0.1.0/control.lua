local RESPONSE_PREFIX = "__AUTO_FACTORY__"

local DIRECTIONS = {
  north = defines.direction.north,
  east = defines.direction.east,
  south = defines.direction.south,
  west = defines.direction.west,
}

local DIRECTION_NAMES = {}
for name, value in pairs(defines.direction) do
  DIRECTION_NAMES[value] = name
end

local STATUS_NAMES = {}
for name, value in pairs(defines.entity_status) do
  STATUS_NAMES[value] = name
end

local MAX_ACTION_TICKS = 60 * 60
local STUCK_TICKS = 30
-- Sliding along an obstacle still moves the character, so blocking is judged by
-- progress toward the target. 8-way walking is at worst cos(22.5°) efficient.
local MIN_WALK_PROGRESS = 0.5

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

-- Night darkens screenshots without adding anything the agent should plan around.
local function ensure_world()
  ensure_storage()
  for _, surface in pairs(game.surfaces) do
    surface.always_day = true
  end
end

script.on_init(ensure_world)
script.on_configuration_changed(ensure_world)
script.on_event(defines.events.on_surface_created, function(event)
  game.surfaces[event.surface_index].always_day = true
end)

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

-- Every position crossing the API is an offset from the player, so results can be
-- passed straight back as arguments.
local function position_from(player, params)
  local origin = player.position
  return {
    x = origin.x + required_number(params, "dx"),
    y = origin.y + required_number(params, "dy"),
  }
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

local function offset_from(origin, position)
  return {dx = rounded(position.x - origin.x), dy = rounded(position.y - origin.y)}
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

local function entity_status(entity)
  local ok, status = pcall(function() return entity.status end)
  if ok and status then
    return STATUS_NAMES[status] or status
  end
  return nil
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

local function halt(player)
  player.walking_state = {walking = false, direction = defines.direction.north}
  player.mining_state = {mining = false}
end

local function stop_player(player)
  halt(player)
  storage.actions[player.index] = nil
end

-- Finished actions stay in storage so the caller can read why they ended.
local function finish(player, action, reason)
  halt(player)
  action.done = true
  action.reason = reason
end

local function action_summary(player, action)
  local summary = {
    kind = action.kind,
    done = action.done == true,
    reason = action.reason,
  }
  if action.kind == "walk_to" then
    summary.moved = offset_from(action.start, player.position)
    summary.remaining = offset_from(player.position, action.target)
  elseif action.kind == "mine" then
    summary.target = action.target_name
    summary.requested = action.count
    summary.mined = action.mined
  elseif action.kind == "wait" then
    summary.condition = action.condition
    summary.progress = action.progress
    summary.goal = action.goal
    if action.entity then
      summary.entity = action.entity.valid and action.entity.name or "gone"
      summary.status = action.entity.valid and entity_status(action.entity) or nil
    end
  end
  return summary
end

local function walk_direction(dx, dy, tolerance)
  local east = dx > tolerance
  local west = dx < -tolerance
  local south = dy > tolerance
  local north = dy < -tolerance
  if north and east then return defines.direction.northeast end
  if north and west then return defines.direction.northwest end
  if south and east then return defines.direction.southeast end
  if south and west then return defines.direction.southwest end
  if north then return defines.direction.north end
  if south then return defines.direction.south end
  if east then return defines.direction.east end
  if west then return defines.direction.west end
  return nil
end

local function tick_walk_to(player, action)
  local position = player.position
  -- One tick of movement must not jump across the arrival window.
  local tolerance = math.max(0.3, player.character_running_speed)
  local direction = walk_direction(
    action.target.x - position.x,
    action.target.y - position.y,
    tolerance
  )
  if not direction then
    finish(player, action, "arrived")
    return
  end
  local remaining = math.sqrt(distance_squared(position, action.target))
  if not action.checkpoint_tick then
    action.checkpoint_tick = game.tick
    action.checkpoint_remaining = remaining
  elseif game.tick - action.checkpoint_tick >= STUCK_TICKS then
    local expected = player.character_running_speed * (game.tick - action.checkpoint_tick)
    if action.checkpoint_remaining - remaining < expected * MIN_WALK_PROGRESS then
      finish(player, action, "blocked")
      return
    end
    action.checkpoint_tick = game.tick
    action.checkpoint_remaining = remaining
  end
  player.walking_state = {walking = true, direction = direction}
end

local function tick_mine(player, action)
  player.update_selected_entity(action.position)
  local target = player.selected
  if not target or not target.valid or target.name ~= action.target_name then
    finish(player, action, "target gone")
  elseif not player.can_reach_entity(target) then
    finish(player, action, "out of reach")
  else
    player.mining_state = {mining = true, position = action.position}
  end
end

-- Returns the current value of a wait condition, or nil once its entity is gone.
local function wait_progress(player, action)
  local entity = action.entity
  if entity and not entity.valid then
    return nil
  end
  if action.condition == "crafts" then
    return entity.products_finished - action.baseline
  elseif action.condition == "items" then
    local contents = entity and entity_contents(entity)
      or inventory_contents(player.get_main_inventory())
    return contents[action.item] or 0
  else
    return player.crafting_queue_size
  end
end

local function tick_wait(player, action)
  local progress = wait_progress(player, action)
  if progress == nil then
    finish(player, action, "entity gone")
    return
  end
  action.progress = progress
  local met
  if action.condition == "handcraft" then
    met = progress == 0
  else
    met = progress >= action.goal
  end
  if met then
    finish(player, action, "condition met")
  end
end

script.on_event(defines.events.on_tick, function(event)
  ensure_storage()
  for player_index, action in pairs(storage.actions) do
    local player = game.get_player(player_index)
    if not player or not player.valid or not player.character then
      storage.actions[player_index] = nil
    elseif action.done then
      -- Waiting for the caller to collect the result.
    elseif event.tick >= action.until_tick then
      finish(player, action, "timeout")
    elseif action.kind == "walk_to" then
      tick_walk_to(player, action)
    elseif action.kind == "mine" then
      tick_mine(player, action)
    elseif action.kind == "wait" then
      tick_wait(player, action)
    end
  end
end)

script.on_event(defines.events.on_player_mined_item, function(event)
  ensure_storage()
  local action = storage.actions[event.player_index]
  if not action or action.kind ~= "mine" or action.done then
    return
  end
  local stack = event.item_stack
  action.mined[stack.name] = (action.mined[stack.name] or 0) + stack.count
  action.mined_total = action.mined_total + stack.count
  if action.mined_total >= action.count then
    finish(game.get_player(event.player_index), action, "count reached")
  end
end)

local function research_state(force)
  local current = force.current_research
  local queue = {}
  for _, technology in pairs(force.research_queue or {}) do
    table.insert(queue, technology.name)
  end
  local available = {}
  local triggers = {}
  for name, technology in pairs(force.technologies) do
    if technology.enabled and not technology.researched then
      local ready = true
      for _, prerequisite in pairs(technology.prerequisites) do
        if not prerequisite.researched then
          ready = false
          break
        end
      end
      if ready then
        local trigger = technology.prototype.research_trigger
        if trigger then
          triggers[name] = {
            type = trigger.type,
            item = trigger.item and trigger.item.name,
            entity = trigger.entity and (trigger.entity.name or trigger.entity),
            fluid = trigger.fluid,
            count = trigger.count or trigger.amount,
          }
        else
          table.insert(available, name)
        end
      end
    end
  end
  table.sort(available)
  return {
    current = current and current.name,
    progress = current and rounded(force.research_progress),
    queue = queue,
    available = available,
    triggers = triggers,
  }
end

local function entity_entry(entity, origin)
  local entry = {
    name = entity.name,
    type = entity.type,
    position = offset_from(origin, entity.position),
  }
  if entity.supports_direction then
    entry.direction = DIRECTION_NAMES[entity.direction]
  end
  if entity.type == "resource" then
    entry.amount = entity.amount
  end
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
  entry.status = entity_status(entity)
  return entry
end

local function entity_amount(entity)
  if entity.type == "resource" then
    return entity.amount
  end
  local total = 0
  for _, count in pairs(entity_contents(entity)) do
    total = total + count
  end
  return total
end

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
      summary.nearest = offset_from(player.position, entity.position)
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
  local origin = player.position
  for _, entity in pairs(nearby) do
    table.insert(entities, entity_entry(entity, origin))
  end

  local action = storage.actions[player.index]
  local action_state = action and action_summary(player, action)
  return {
    tick = game.tick,
    speed = game.speed,
    player = {
      index = player.index,
      name = player.name,
      world_position = plain_position(player.position),
      health = player.character.health,
      inventory = inventory_contents(player.get_main_inventory()),
      crafting_queue_size = player.crafting_queue_size,
      crafting_progress = rounded(player.crafting_queue_progress),
      action = action_state,
    },
    research = research_state(player.force),
    radius = radius,
    resources = resources,
    entities = entities,
  }
end

local FIND_SORTS = {distance = true, amount = true, name = true}

-- Substring names are resolved to prototypes so the engine does the spatial filtering.
local function matching_entity_names(fragment)
  local names = {}
  for name in pairs(prototypes.entity) do
    if string.find(name, fragment, 1, true) then
      table.insert(names, name)
    end
  end
  if #names == 0 then
    fail("no entity prototype name contains " .. fragment)
  end
  return names
end

-- The engine returns nothing for an unknown type, which reads as "none nearby".
local function check_entity_type(entity_type)
  for _, prototype in pairs(prototypes.entity) do
    if prototype.type == entity_type then
      return
    end
  end
  fail("unknown entity type: " .. entity_type)
end

function handlers.find(params)
  local player = get_player(params)
  local radius = math.max(1, math.min(256, required_number(params, "radius")))
  local limit = math.max(1, math.min(50, math.floor(required_number(params, "limit"))))
  local sort = params.sort or "distance"
  if not FIND_SORTS[sort] then
    fail("sort must be distance, amount, or name")
  end
  local name = params.name or ""
  local entity_type = params.type or ""
  local status = params.status or ""
  if name == "" and entity_type == "" then
    fail("give a name or type filter")
  end

  local filter = {position = player.position, radius = radius}
  if name ~= "" then
    filter.name = matching_entity_names(name)
  end
  if entity_type ~= "" then
    check_entity_type(entity_type)
    filter.type = entity_type
  end
  local found_ok, found = pcall(player.surface.find_entities_filtered, filter)
  if not found_ok then
    fail(tostring(found))
  end

  local origin = player.position
  local matches = {}
  local totals = {}
  for _, entity in pairs(found) do
    if entity.valid and (status == "" or entity_status(entity) == status) then
      local match = {
        entity = entity,
        distance = distance_squared(origin, entity.position),
        amount = sort == "amount" and entity_amount(entity) or nil,
      }
      table.insert(matches, match)
      local total = totals[entity.name]
      if not total then
        total = {count = 0}
        totals[entity.name] = total
      end
      total.count = total.count + 1
      if entity.type == "resource" then
        total.amount = (total.amount or 0) + entity.amount
      end
    end
  end

  if sort == "distance" then
    table.sort(matches, function(a, b) return a.distance < b.distance end)
  elseif sort == "amount" then
    table.sort(matches, function(a, b)
      if a.amount ~= b.amount then return a.amount > b.amount end
      return a.distance < b.distance
    end)
  else
    table.sort(matches, function(a, b)
      if a.entity.name ~= b.entity.name then return a.entity.name < b.entity.name end
      return a.distance < b.distance
    end)
  end

  local entities = {}
  for index = 1, math.min(limit, #matches) do
    local match = matches[index]
    local entry = entity_entry(match.entity, origin)
    entry.distance = rounded(math.sqrt(match.distance))
    table.insert(entities, entry)
  end
  return {
    radius = radius,
    matched = #matches,
    totals = totals,
    entities = entities,
  }
end

function handlers.walk_to(params)
  local player = get_player(params)
  local dx = math.max(-100, math.min(100, required_number(params, "dx")))
  local dy = math.max(-100, math.min(100, required_number(params, "dy")))
  local start = player.position
  stop_player(player)
  storage.actions[player.index] = {
    kind = "walk_to",
    start = {x = start.x, y = start.y},
    target = {x = start.x + dx, y = start.y + dy},
    until_tick = game.tick + MAX_ACTION_TICKS,
  }
  return action_summary(player, storage.actions[player.index])
end

function handlers.mine(params)
  local player = get_player(params)
  local position = position_from(player, params)
  local count = math.max(1, math.min(500, math.floor(required_number(params, "count"))))
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
    target_name = target.name,
    count = count,
    mined = {},
    mined_total = 0,
    until_tick = game.tick + MAX_ACTION_TICKS,
  }
  return action_summary(player, storage.actions[player.index])
end

local WAIT_CONDITIONS = {crafts = true, items = true, handcraft = true}

function handlers.wait(params)
  local player = get_player(params)
  local condition = required_string(params, "condition")
  if not WAIT_CONDITIONS[condition] then
    fail("condition must be crafts, items, or handcraft")
  end
  local seconds = math.max(1, math.min(60, required_number(params, "seconds")))
  local action = {
    kind = "wait",
    condition = condition,
    until_tick = game.tick + math.floor(seconds * 60),
  }
  local name = params.entity or ""
  if condition == "crafts" or (condition == "items" and name ~= "") then
    if name == "" then
      fail("crafts needs an entity")
    end
    action.entity = find_entity(player, name, position_from(player, params))
  end
  if condition == "crafts" then
    local ok, finished = pcall(function() return action.entity.products_finished end)
    if not ok then
      fail(name .. " does not count finished crafts; wait for items instead")
    end
    action.baseline = finished
  end
  if condition == "items" then
    action.item = required_string(params, "item")
  end
  if condition ~= "handcraft" then
    action.goal = math.max(1, math.floor(required_number(params, "count")))
  end
  stop_player(player)
  storage.actions[player.index] = action
  tick_wait(player, action)
  return action_summary(player, action)
end

function handlers.status(params)
  local player = get_player(params)
  local action = storage.actions[player.index]
  return action and action_summary(player, action) or {done = true}
end

function handlers.stop(params)
  local player = get_player(params)
  local action = storage.actions[player.index]
  if not action then
    return {done = true}
  end
  if not action.done then
    finish(player, action, "stopped")
  end
  local summary = action_summary(player, action)
  stop_player(player)
  return summary
end

function handlers.rotate(params)
  local player = get_player(params)
  local name = required_string(params, "entity")
  local entity = find_entity(player, name, position_from(player, params))
  if not player.can_reach_entity(entity) then
    fail("the entity is outside reach")
  end
  if not entity.rotate {reverse = params.reverse == true, by_player = player} then
    fail("Factorio did not rotate the " .. name .. "; it may not be rotatable")
  end
  return {
    entity = name,
    position = offset_from(player.position, entity.position),
    direction = DIRECTION_NAMES[entity.direction],
  }
end

function handlers.research(params)
  local player = get_player(params)
  local name = required_string(params, "technology")
  local force = player.force
  local technology = force.technologies[name]
  if not technology then
    fail("unknown technology: " .. name)
  end
  if technology.researched then
    fail(name .. " is already researched")
  end
  if technology.prototype.research_trigger then
    fail(name .. " is unlocked by its trigger, not by labs")
  end
  if not force.add_research(technology) then
    fail("could not queue " .. name .. "; check that its prerequisites are researched")
  end
  return research_state(force)
end

-- Expected count per craft or mining cycle, so chance-based products compare fairly.
local function expected_amount(product)
  local amount = product.amount or (product.amount_min + product.amount_max) / 2
  local probability = product.probability or product.independent_probability or 1
  return (amount + (product.extra_count_fraction or 0)) * probability
end

local function amounts(list)
  local result = {}
  for _, entry in pairs(list or {}) do
    result[entry.name] = rounded((result[entry.name] or 0) + expected_amount(entry))
  end
  return result
end

local function power_needs(prototype)
  local source = "none"
  if prototype.burner_prototype then
    source = "burner"
  elseif prototype.electric_energy_source_prototype then
    source = "electric"
  elseif prototype.fluid_energy_source_prototype then
    source = "fluid"
  elseif prototype.heat_energy_source_prototype then
    source = "heat"
  end
  return source, prototype.energy_usage and rounded(prototype.energy_usage * 60 / 1000)
end

-- Items the force can already make, so the agent knows which machines it can build.
local function craftable_items(force)
  local items = {}
  for _, recipe in pairs(force.recipes) do
    if recipe.enabled then
      for _, product in pairs(recipe.prototype.products) do
        items[product.name] = true
      end
    end
  end
  return items
end

-- The character is listed as "hand"; it needs no power and is never built.
local function machine_entry(prototype, craftable, speed, seconds_per_cycle, amount)
  local seconds = seconds_per_cycle / speed
  local entry = {
    speed = rounded(speed),
    seconds = rounded(seconds),
    per_minute = rounded(amount * 60 / seconds),
  }
  if prototype.type ~= "character" then
    entry.energy, entry.kw = power_needs(prototype)
    entry.buildable = craftable[prototype.items_to_place_this[1].name] == true
  end
  return entry
end

-- Unplaceable machines such as crash-site wrecks would only mislead.
local function usable_machine(prototype)
  if prototype.hidden then
    return false
  end
  return prototype.type == "character" or next(prototype.items_to_place_this or {}) ~= nil
end

local function runs_recipe(prototype, recipe)
  for _, category in pairs(recipe.categories) do
    if prototype.crafting_categories[category] then
      return true
    end
  end
  return false
end

local function machine_key(prototype)
  return prototype.type == "character" and "hand" or prototype.name
end

local function unlocking_technologies(recipe_name)
  local names = {}
  for name, technology in pairs(prototypes.technology) do
    for _, effect in pairs(technology.effects or {}) do
      if effect.type == "unlock-recipe" and effect.recipe == recipe_name then
        table.insert(names, name)
      end
    end
  end
  return names
end

local function similar_names(fragment)
  local names = {}
  for _, table_of in pairs {prototypes.item, prototypes.fluid} do
    for name in pairs(table_of) do
      if string.find(name, fragment, 1, true) then
        table.insert(names, name)
      end
    end
  end
  table.sort(names)
  return {table.unpack(names, 1, 10)}
end

function handlers.recipe(params)
  local player = get_player(params)
  local name = required_string(params, "item")
  if not prototypes.item[name] and not prototypes.fluid[name] then
    local similar = similar_names(name)
    if #similar == 0 then
      fail("unknown item or fluid: " .. name)
    end
    fail("unknown item or fluid: " .. name .. "; similar: " .. table.concat(similar, ", "))
  end
  local force = player.force
  local craftable = craftable_items(force)
  local character = player.character.prototype

  local crafters = {}
  local miners = {}
  for _, prototype in pairs(prototypes.entity) do
    local is_player = prototype.type == "character"
    if usable_machine(prototype) and (not is_player or prototype.name == character.name) then
      if prototype.crafting_categories then
        table.insert(crafters, prototype)
      end
      if prototype.resource_categories then
        table.insert(miners, prototype)
      end
    end
  end

  local recipes = {}
  for recipe_name, recipe in pairs(prototypes.recipe) do
    local made = amounts(recipe.products)[name]
    -- Emptying a barrel only returns fluid that was already made elsewhere.
    if made and not recipe.hidden and recipe.subgroup.name ~= "empty-barrel" then
      local machines = {}
      for _, prototype in pairs(crafters) do
        if runs_recipe(prototype, recipe) then
          machines[machine_key(prototype)] = machine_entry(
            prototype, craftable, prototype.get_crafting_speed(), recipe.energy, made
          )
        end
      end
      local entry = {
        unlocked = force.recipes[recipe_name].enabled,
        categories = recipe.categories,
        seconds = rounded(recipe.energy),
        ingredients = amounts(recipe.ingredients),
        products = amounts(recipe.products),
        machines = machines,
      }
      local technologies = not entry.unlocked and unlocking_technologies(recipe_name)
      if technologies and #technologies > 0 then
        entry.unlocked_by = technologies
      end
      recipes[recipe_name] = entry
    end
  end

  local mining = {}
  for resource_name, resource in pairs(prototypes.entity) do
    local mineable = resource.type == "resource" and resource.mineable_properties
    local made = mineable and mineable.minable and amounts(mineable.products)[name]
    if made then
      local drills = {}
      for _, prototype in pairs(miners) do
        if prototype.resource_categories[resource.resource_category] then
          drills[machine_key(prototype)] = machine_entry(
            prototype, craftable, prototype.mining_speed, mineable.mining_time, made
          )
        end
      end
      mining[resource_name] = {
        seconds = rounded(mineable.mining_time),
        required_fluid = mineable.required_fluid,
        -- Oil-like fields scale output by their yield, which the base rate ignores.
        rate_scales_with_yield = resource.infinite_resource or nil,
        machines = drills,
      }
    end
  end

  if next(recipes) == nil and next(mining) == nil then
    fail("nothing makes " .. name)
  end
  return {item = name, recipes = recipes, mining = mining}
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
  local position = position_from(player, params)
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
  return {
    placed = item,
    position = offset_from(player.position, position),
    direction = params.direction,
  }
end

function handlers.insert(params)
  local player = get_player(params)
  local name = required_string(params, "entity")
  local item = required_string(params, "item")
  local count = math.max(1, math.floor(required_number(params, "count")))
  local entity = find_entity(player, name, position_from(player, params))
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
  local entity = find_entity(player, name, position_from(player, params))
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
  ensure_world()
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
