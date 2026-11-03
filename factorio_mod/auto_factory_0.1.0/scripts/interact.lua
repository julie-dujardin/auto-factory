local common = require("scripts.common")
local entities = require("scripts.entities")
local ids = require("scripts.ids")

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

local function empty_cursor(player)
  local cursor = player.cursor_stack
  if not cursor or cursor.valid_for_read then
    common.fail("the player cursor must be empty")
  end
  return cursor
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
    return "the item cannot be built at that position"
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

function handlers.insert(params)
  local player = common.get_player(params)
  local item = ids.check(common.required_string(params, "item"), "item")
  local count = math.max(1, math.floor(common.required_number(params, "count")))
  local name, entity = reachable_entity(player, params)
  local inventory = player.get_main_inventory()
  local removed = inventory.remove {name = item, count = count}
  local inserted = entity.insert {name = item, count = removed}
  if inserted < removed then
    inventory.insert {name = item, count = removed - inserted}
  end
  return {entity = name, item = item, requested = count, inserted = inserted}
end

function handlers.take(params)
  local player = common.get_player(params)
  local item = ids.check(common.required_string(params, "item"), "item")
  local count = math.max(1, math.floor(common.required_number(params, "count")))
  local name, entity = reachable_entity(player, params)
  local removed = entity.remove_item {name = item, count = count}
  local inserted = player.get_main_inventory().insert {name = item, count = removed}
  if inserted < removed then
    entity.insert {name = item, count = removed - inserted}
  end
  return {entity = name, item = item, requested = count, taken = inserted}
end

return {handlers = handlers}
