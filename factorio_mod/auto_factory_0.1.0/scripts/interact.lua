local common = require("scripts.common")
local entities = require("scripts.entities")

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
  local recipe = common.required_string(params, "recipe")
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

function handlers.place(params)
  local player = common.get_player(params)
  local item = common.required_string(params, "item")
  local position = common.position_from(player, params)
  local direction = common.direction_from(params)
  if common.distance_squared(player.position, position) > player.build_distance ^ 2 then
    common.fail("the position is outside build reach")
  end
  local cursor = player.cursor_stack
  if not cursor or cursor.valid_for_read then
    common.fail("the player cursor must be empty before API placement")
  end
  local source = player.get_main_inventory().find_item_stack(item)
  if not source then
    common.fail("the player has no " .. item)
  end
  if not cursor.transfer_stack(source, 1) then
    common.fail("could not move " .. item .. " into the cursor")
  end
  if not player.can_build_from_cursor {position = position, direction = direction} then
    restore_cursor(player)
    common.fail("the item cannot be built at that position")
  end
  local before = cursor.count
  player.build_from_cursor {position = position, direction = direction}
  local remaining = cursor.valid_for_read and cursor.count or 0
  restore_cursor(player)
  if remaining >= before then
    common.fail("Factorio did not place the item")
  end
  return {
    placed = item,
    position = common.offset_from(player.position, position),
    direction = params.direction,
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
  local item = common.required_string(params, "item")
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
  local item = common.required_string(params, "item")
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
