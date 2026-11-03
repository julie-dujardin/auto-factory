local common = require("scripts.common")
local entities = require("scripts.entities")
local ids = require("scripts.ids")
local recipes = require("scripts.recipes")

local handlers = {}

local function reachable_entity(player, params)
  local name = common.required_string(params, "entity")
  local entity = entities.find(player, name, common.position_from(player, params))
  if not player.can_reach_entity(entity) then
    common.fail("the entity is outside reach")
  end
  return name, entity
end

function handlers.craft(params)
  local player = common.get_player(params)
  local recipe = ids.check(common.required_string(params, "recipe"), "recipe")
  local count = math.max(1, math.min(100, math.floor(common.required_number(params, "count"))))
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

local MAX_LINE = 50

-- Puts what the cursor holds back into the inventory, as pressing Q does.
local function empty_cursor(player)
  if not player.clear_cursor() then
    common.fail("the cursor holds items that do not fit in the inventory")
  end
  return player.cursor_stack
end

local function line_count(params)
  return math.max(1, math.min(MAX_LINE, math.floor(common.required_number(params, "count"))))
end

local function line_position(start, line, spacing, index)
  local step = common.DIRECTION_STEPS[line]
  return {x = start.x + step.x * spacing * index, y = start.y + step.y * spacing * index}
end

local function placed_entity(item)
  return prototypes.item[ids.check(item, "item")].place_result
end

local function footprint(entity, direction)
  if not entity then
    return 1, 1
  end
  if direction == defines.direction.east or direction == defines.direction.west then
    return entity.tile_height, entity.tile_width
  end
  return entity.tile_width, entity.tile_height
end

-- Where the engine centres a footprint of this size built at value.
local function snap(value, size)
  if size % 2 == 1 then
    return math.floor(value) + 0.5
  end
  return math.floor(value + 0.5)
end

local OBSTRUCTIONS_LISTED = 5

-- Names what keeps entity from being built at position, or nil when it is unclear.
local function obstruction(player, entity, position, direction)
  if not entity then
    return nil
  end
  local width, height = footprint(entity, direction)
  -- Shrunk so neighbours touching the footprint's edges are not counted.
  local area = {
    left_top = {x = position.x - width / 2 + 0.1, y = position.y - height / 2 + 0.1},
    right_bottom = {x = position.x + width / 2 - 0.1, y = position.y + height / 2 - 0.1},
  }
  local layers = {}
  for layer in pairs(entity.collision_mask.layers) do
    table.insert(layers, layer)
  end
  local surface = player.surface
  local blockers = {}
  local character_there = false
  for _, other in pairs(common.nearest_first(
    surface.find_entities_filtered {area = area, collision_mask = layers},
    position
  )) do
    if other == player.character then
      character_there = true
    elseif #blockers < OBSTRUCTIONS_LISTED then
      table.insert(blockers, other.name .. " at " .. common.offset_text(player.position, other.position))
    end
  end
  if #blockers > 0 then
    return "blocked by " .. table.concat(blockers, ", ")
  end
  local tiles = surface.find_tiles_filtered {area = area, collision_mask = layers, limit = 1}
  if #tiles > 0 then
    return "blocked by " .. tiles[1].name .. " tiles"
  end
  if entity.type == "mining-drill" then
    local radius = entity.mining_drill_radius
    local ore = surface.count_entities_filtered {
      area = {
        left_top = {x = position.x - radius, y = position.y - radius},
        right_bottom = {x = position.x + radius, y = position.y + radius},
      },
      type = "resource",
      limit = 1,
    }
    if ore == 0 then
      return "a mining drill needs ore in its mining area"
    end
  end
  if character_there then
    return "the player stands there"
  end
  return nil
end

-- Building refills the cursor from the inventory, so only the total shows a placement.
local function held_count(player, cursor, item)
  local held = cursor.valid_for_read and cursor.name == item and cursor.count or 0
  return player.get_main_inventory().get_item_count(item) + held
end

-- Returns why the item could not be placed, or nil once it is.
local function place_one(player, cursor, item, entity, position, direction)
  if common.distance_squared(player.position, position) > player.build_distance ^ 2 then
    return "the position is outside build reach"
  end
  -- Building onto the same entity rotates it in place.
  if entity and player.surface.find_entity(entity.name, position) then
    return "a " .. entity.name .. " is already there; use api_rotate to turn it"
  end
  local source = player.get_main_inventory().find_item_stack(item)
  if not source then
    return "the player has no " .. item
  end
  if not cursor.transfer_stack(source, 1) then
    return "could not move " .. item .. " into the cursor"
  end
  if not player.can_build_from_cursor {position = position, direction = direction} then
    restore_cursor(player)
    local reason = obstruction(player, entity, position, direction)
    return "the item cannot be built at " .. common.offset_text(player.position, position)
      .. (reason and ": " .. reason or "")
  end
  local before = held_count(player, cursor, item)
  player.build_from_cursor {position = position, direction = direction}
  local placed = held_count(player, cursor, item) < before
  restore_cursor(player)
  if not placed then
    return "Factorio did not place the item"
  end
end

function handlers.place(params)
  local player = common.get_player(params)
  local item = common.required_string(params, "item")
  local direction = common.direction_from(params, "direction")
  local line = common.direction_from(params, "line_direction")
  local count = line_count(params)
  local cursor = empty_cursor(player)
  local entity = placed_entity(item)
  local width, height = footprint(entity, direction)
  local start = common.position_from(player, params)
  start = {x = snap(start.x, width), y = snap(start.y, height)}
  -- Copies sit edge to edge.
  local spacing = height
  if line == defines.direction.east or line == defines.direction.west then
    spacing = width
  end
  local placed, stopped = 0, nil
  for index = 0, count - 1 do
    local position = line_position(start, line, spacing, index)
    stopped = place_one(player, cursor, item, entity, position, direction)
    if stopped then
      break
    end
    placed = placed + 1
  end
  if placed == 0 then
    common.fail(stopped)
  end
  return {
    placed = item,
    count = placed,
    position = common.offset_from(player.position, start),
    last = common.offset_from(player.position, line_position(start, line, spacing, placed - 1)),
    direction = params.direction,
    stopped = stopped,
  }
end

-- Drag-building, with its automatic undergrounds, is engine input handling that Lua
-- cannot trigger: drag_prepare loads the cursor and plans the line, the harness drags
-- the real mouse, and drag_finish empties the cursor and reports what was built.
local DRAG_TYPES = {["transport-belt"] = true, ["pipe"] = true}

function handlers.drag_prepare(params)
  local player = common.get_player(params)
  local item = common.required_string(params, "item")
  local line = common.direction_from(params, "direction")
  local count = line_count(params)
  if player.controller_type ~= defines.controllers.character
    or player.render_mode ~= defines.render_mode.game then
    common.fail("the camera must be following the character")
  end
  local entity = placed_entity(item)
  if not entity or not DRAG_TYPES[entity.type] then
    common.fail(item .. " is not a belt or pipe; use api_place")
  end
  local cursor = empty_cursor(player)
  local inventory = player.get_main_inventory()
  local source = inventory.find_item_stack(item)
  if not source then
    common.fail("the player has no " .. item)
  end
  -- Tile centres keep the pointer clear of tile edges.
  local start = common.position_from(player, params)
  start = {x = snap(start.x, 1), y = snap(start.y, 1)}
  local tiles = 0
  while tiles < count
    and common.distance_squared(player.position, line_position(start, line, 1, tiles))
      <= player.build_distance ^ 2 do
    tiles = tiles + 1
  end
  if tiles == 0 then
    common.fail("the start is outside build reach")
  end
  local finish = line_position(start, line, 1, tiles - 1)
  storage.drags = storage.drags or {}
  storage.drags[player.index] = {
    item = item,
    requested = count,
    tiles = tiles,
    finish = finish,
    before = entities.inventory_contents(inventory),
  }
  player.opened = nil
  -- At zoom 1 the whole build reach is on screen.
  player.zoom = 1
  cursor.transfer_stack(source)
  return {
    start = common.offset_from(player.position, start),
    finish = common.offset_from(player.position, finish),
    tiles = tiles,
    zoom = 1,
    resolution = player.display_resolution,
  }
end

function handlers.drag_finish(params)
  local player = common.get_player(params)
  local drag = storage.drags and storage.drags[player.index]
  if not drag then
    common.fail("no drag is in progress")
  end
  storage.drags[player.index] = nil
  player.clear_cursor()
  local after = entities.inventory_contents(player.get_main_inventory())
  local placed = {}
  local built = false
  for name, count in pairs(drag.before) do
    local used = count - (after[name] or 0)
    if used > 0 then
      placed[name] = used
      built = true
    end
  end
  if not built then
    common.fail("nothing was built; the start tile may be blocked")
  end
  return {
    item = drag.item,
    placed = placed,
    finish = common.offset_from(player.position, drag.finish),
    stopped = drag.tiles < drag.requested and "the rest is outside build reach" or nil,
  }
end

function handlers.rotate(params)
  local player = common.get_player(params)
  local name, entity = reachable_entity(player, params)
  if not entity.rotate {reverse = params.reverse == true, by_player = player} then
    common.fail("Factorio did not rotate the " .. name .. "; it may not be rotatable")
  end
  return {
    entity = name,
    position = common.offset_from(player.position, entity.position),
    direction = common.DIRECTION_NAMES[entity.direction],
  }
end

function handlers.set_recipe(params)
  local player = common.get_player(params)
  local recipe = ids.check(common.required_string(params, "recipe"), "recipe")
  local name, entity = reachable_entity(player, params)
  if entity.type ~= "assembling-machine" then
    common.fail(name .. " is a " .. entity.type .. "; only assembling machines take a recipe")
  end
  if entity.recipe_locked then
    common.fail(name .. " has a fixed recipe")
  end
  if not recipes.runs_recipe(entity.prototype, prototypes.recipe[recipe]) then
    common.fail(name .. " cannot craft " .. recipe .. "; api_recipe lists the machines that can")
  end
  if not player.force.recipes[recipe].enabled then
    common.fail(recipe .. " is not unlocked; api_recipe lists the technology that unlocks it")
  end
  -- Ingredients of the previous recipe come out of the machine.
  local returned = {}
  local inventory = player.get_main_inventory()
  for _, stack in pairs(entity.set_recipe(recipe)) do
    local inserted = inventory.insert(stack)
    if inserted < stack.count then
      player.surface.spill_item_stack {
        position = player.position,
        stack = {name = stack.name, count = stack.count - inserted, quality = stack.quality},
        enable_looted = true,
      }
    end
    returned[stack.name] = (returned[stack.name] or 0) + stack.count
  end
  return {
    entity = name,
    position = common.offset_from(player.position, entity.position),
    recipe = recipe,
    returned = returned,
  }
end

function handlers.insert(params)
  local player = common.get_player(params)
  local item = ids.check(common.required_string(params, "item"), "item")
  local count = math.max(1, math.floor(common.required_number(params, "count")))
  local name, entity = reachable_entity(player, params)
  if entity.type == "assembling-machine" and not entity.get_recipe() then
    common.fail(name .. " has no recipe, so it accepts no ingredients; use api_set_recipe")
  end
  local inventory = player.get_main_inventory()
  local removed = inventory.remove {name = item, count = count}
  local inserted = entity.insert {name = item, count = removed}
  if inserted < removed then
    inventory.insert {name = item, count = removed - inserted}
  end
  return {entity = name, item = item, requested = count, inserted = inserted}
end

-- An empty item takes everything the entity holds.
function handlers.take(params)
  local player = common.get_player(params)
  local item = params.item or ""
  local wanted = {}
  if item ~= "" then
    wanted[ids.check(item, "item")] = math.max(1, math.floor(common.required_number(params, "count")))
  end
  local name, entity = reachable_entity(player, params)
  local taken = {}
  if entity.type == "item-entity" then
    local stack = entity.stack
    if item ~= "" and stack.name ~= item then
      common.fail("that " .. name .. " is " .. stack.name)
    end
    local picked, count = stack.name, stack.count
    if not player.mine_entity(entity) then
      common.fail("could not pick up the " .. picked)
    end
    taken[picked] = count
    return {entity = name, taken = taken}
  end
  if item == "" then
    wanted = entities.contents(entity)
  end
  local inventory = player.get_main_inventory()
  for wanted_item, count in pairs(wanted) do
    local removed = entity.remove_item {name = wanted_item, count = count}
    if removed > 0 then
      local inserted = inventory.insert {name = wanted_item, count = removed}
      if inserted < removed then
        entity.insert {name = wanted_item, count = removed - inserted}
      end
      if inserted > 0 then
        taken[wanted_item] = inserted
      end
    end
  end
  return {entity = name, taken = taken}
end

return {handlers = handlers}
