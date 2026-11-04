local common = require("scripts.common")
local entities = require("scripts.entities")
local ids = require("scripts.ids")
local info = require("scripts.info")
local layout = require("scripts.layout")
local recipes = require("scripts.recipes")

local handlers = {}

local function reachable_entity(player, params)
  local entity = entities.target(player, params)
  if not player.can_reach_entity(entity) then
    common.fail("the entity is outside reach")
  end
  return entity.name, entity
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

local OBSTRUCTIONS_LISTED = 5

-- Names what keeps entity from being built at position, or nil when it is unclear.
local function obstruction(player, entity, position, direction)
  if not entity then
    return nil
  end
  local width, height = layout.footprint(entity, direction)
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
      table.insert(blockers, other.name .. " at " .. common.offset_text(common.origin(player), other.position))
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

-- Clearance between the character and a footprint it steps out of.
local STEP_CLEARANCE = 0.1

-- Moves the character just clear of area, as a player steps aside to build where they
-- stand.
local function step_aside(player, area)
  local character = player.character
  local box = character.bounding_box
  if not layout.overlaps(box, area) then
    return
  end
  local half_width = (box.right_bottom.x - box.left_top.x) / 2 + STEP_CLEARANCE
  local half_height = (box.right_bottom.y - box.left_top.y) / 2 + STEP_CLEARANCE
  local here = character.position
  local steps = common.nearest_first({
    {position = {x = area.left_top.x - half_width, y = here.y}},
    {position = {x = area.right_bottom.x + half_width, y = here.y}},
    {position = {x = here.x, y = area.left_top.y - half_height}},
    {position = {x = here.x, y = area.right_bottom.y + half_height}},
  }, here)
  for _, step in pairs(steps) do
    local spot = player.surface.find_non_colliding_position(character.name, step.position, 1, 0.1)
    if spot and not layout.overlaps(layout.area(spot, 2 * half_width, 2 * half_height), area) then
      character.teleport(spot)
      return
    end
  end
end

-- Returns why the item could not be placed, or nil and the built entity.
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
  if entity then
    local width, height = layout.footprint(entity, direction)
    step_aside(player, layout.area(position, width, height))
  end
  if not cursor.transfer_stack(source, 1) then
    return "could not move " .. item .. " into the cursor"
  end
  if not player.can_build_from_cursor {position = position, direction = direction} then
    restore_cursor(player)
    local reason = obstruction(player, entity, position, direction)
    return "the item cannot be built at " .. common.offset_text(common.origin(player), position)
      .. (reason and ": " .. reason or "")
  end
  local before = held_count(player, cursor, item)
  player.build_from_cursor {position = position, direction = direction}
  local placed = held_count(player, cursor, item) < before
  restore_cursor(player)
  if not placed then
    return "Factorio did not place the item"
  end
  return nil, entity and player.surface.find_entity(entity.name, position)
end

-- Belt and pipe lines' middle tiles only link each other.
local LINE_TYPES = {["transport-belt"] = true, pipe = true}

-- What each built entity connects to.
local function built_links(player, built)
  local shown = built
  if #built > 2 and LINE_TYPES[built[1].type] then
    shown = {built[1], built[#built]}
  end
  local result = {}
  for _, entity in pairs(shown) do
    table.insert(result, entities.links(entity, common.origin(player)))
  end
  return #result > 0 and result or nil
end

-- The player's tile once building moved it off stood, else nil.
local function stepped_to(player, stood)
  local now = common.player_position(player)
  if now.dx ~= stood.dx or now.dy ~= stood.dy then
    return now
  end
  return nil
end

-- Placements closer than this to the asked position are not reported as snapped.
local SNAP_REPORTED = 0.25

-- "any" builds facing north, for entities whose facing moves no items.
local function placing_direction(entity, params)
  if params.direction ~= "any" then
    return common.direction_from(params, "direction")
  end
  if entity and info.directional(entity) == true then
    common.fail(
      entity.name .. " needs direction north, east, south, or west; api_entity_info says what its facing changes"
    )
  end
  return defines.direction.north
end

function handlers.place(params)
  local player = common.get_player(params)
  local item = common.required_string(params, "item")
  local entity = placed_entity(item)
  local direction = placing_direction(entity, params)
  local line = common.direction_from(params, "line_direction")
  local count = line_count(params)
  local cursor = empty_cursor(player)
  local width, height = layout.footprint(entity, direction)
  local start, requested = layout.start(player, params, width, height)
  local stood = common.player_position(player)
  -- Copies sit edge to edge.
  local spacing = height
  if line == defines.direction.east or line == defines.direction.west then
    spacing = width
  end
  -- Tiles count as placed but build no entity.
  local placed, built, stopped = 0, {}, nil
  for index = 0, count - 1 do
    local position = line_position(start, line, spacing, index)
    local reason, built_entity = place_one(player, cursor, item, entity, position, direction)
    if reason then
      stopped = reason
      break
    end
    placed = placed + 1
    table.insert(built, built_entity)
  end
  if placed == 0 then
    common.fail(stopped)
  end
  local origin = common.origin(player)
  local result = {
    placed = item,
    count = placed,
    position = common.offset_from(origin, start),
    last = common.offset_from(origin, line_position(start, line, spacing, placed - 1)),
    direction = "any",
    stopped = stopped,
    built = built_links(player, built),
    stepped_aside = stepped_to(player, stood),
  }
  if entity then
    result.direction, result.pipes_face = info.shown_facing(entity, direction)
  end
  if requested and common.distance_squared(requested, start) >= SNAP_REPORTED ^ 2 then
    result.snapped_from = common.offset_from(origin, requested)
  end
  return result
end

-- Spots where an inserter or pole of item connects the entities params name, and how
-- many of them to build.
local function connect_spots(item, entity, params)
  local pickup_from = math.floor(tonumber(params.pickup_from) or 0)
  local drop_into = math.floor(tonumber(params.drop_into) or 0)
  local power = type(params.power) == "table" and params.power or {}
  if pickup_from ~= 0 or drop_into ~= 0 then
    if not entity or entity.type ~= "inserter" then
      common.fail(item .. " is not an inserter; pickup_from and drop_into place inserters")
    end
    if pickup_from == 0 or drop_into == 0 then
      common.fail("an inserter needs both pickup_from and drop_into")
    end
    local spots = layout.inserter_spots(entity, entities.by_id(pickup_from), entities.by_id(drop_into))
    return spots, line_count(params)
  end
  if #power == 0 then
    common.fail("give pickup_from and drop_into for an inserter, or power for an electric pole")
  end
  if not entity or entity.type ~= "electric-pole" then
    common.fail(item .. " is not an electric pole; power places poles")
  end
  local targets = {}
  for _, id in pairs(power) do
    table.insert(targets, entities.by_id(math.floor(tonumber(id) or 0)))
  end
  return layout.pole_spots(entity, targets), 1
end

function handlers.connect(params)
  local player = common.get_player(params)
  local item = common.required_string(params, "item")
  local entity = placed_entity(item)
  local spots, count = connect_spots(item, entity, params)
  local cursor = empty_cursor(player)
  local stood = common.player_position(player)
  local built, first_reason = {}, nil
  for _, spot in ipairs(spots) do
    if #built == count then
      break
    end
    local reason, built_entity = place_one(player, cursor, item, entity, spot.position, spot.direction)
    if reason then
      first_reason = first_reason or reason
    else
      table.insert(built, built_entity)
    end
  end
  if #built == 0 then
    common.fail("none of the " .. #spots .. " fitting spots worked; the best: " .. first_reason)
  end
  local result = {
    placed = item,
    count = #built,
    built = built_links(player, built),
    stepped_aside = stepped_to(player, stood),
  }
  if #built < count then
    result.stopped = "only " .. #built .. " of the " .. #spots .. " fitting spots worked; the best failed: " .. first_reason
  end
  return result
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
  start = {x = layout.snap(start.x, 1), y = layout.snap(start.y, 1)}
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
  -- The harness maps these to screen pixels around the camera, which centres on the
  -- player's exact position.
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
    finish = common.offset_from(common.origin(player), drag.finish),
    stopped = drag.tiles < drag.requested and "the rest is outside build reach" or nil,
  }
end

function handlers.rotate(params)
  local player = common.get_player(params)
  local name, entity = reachable_entity(player, params)
  if not entity.rotate {reverse = params.reverse == true, by_player = player} then
    local directional = info.directional(entity.prototype)
    if not directional then
      common.fail(name .. " has no facing: turning it changes nothing")
    end
    if directional == "fluids_only" and entity.type == "assembling-machine" then
      common.fail(name .. " turns only while its recipe uses fluids: its facing moves only its pipe connections")
    end
    common.fail("Factorio did not rotate the " .. name .. "; it may not be rotatable")
  end
  local direction, pipes_face = info.shown_facing(entity.prototype, entity.direction)
  return {
    entity = name,
    position = common.offset_from(common.origin(player), entity.position),
    direction = direction,
    pipes_face = pipes_face,
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
    position = common.offset_from(common.origin(player), entity.position),
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
