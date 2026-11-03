-- Walking, mining and waiting span many ticks: a handler starts one, on_tick drives
-- it, and the caller polls status until it is done.
local common = require("scripts.common")
local entities = require("scripts.entities")
local ids = require("scripts.ids")

local actions = {handlers = {}}
local handlers = actions.handlers

local MAX_ACTION_TICKS = 60 * 60
local STUCK_TICKS = 30
-- Sliding along an obstacle still moves the character, so blocking is judged by
-- progress toward the target. 8-way walking is at worst cos(22.5°) efficient.
local MIN_WALK_PROGRESS = 0.5

function actions.ensure_storage()
  storage.actions = storage.actions or {}
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

local function summary(player, action)
  local result = {
    kind = action.kind,
    done = action.done == true,
    reason = action.reason,
  }
  if action.kind == "walk_to" then
    result.moved = common.offset_from(action.start, player.position)
    result.remaining = common.offset_from(player.position, action.target)
  elseif action.kind == "mine" then
    result.target = action.target_name
    result.requested = action.count
    result.mined = action.mined
  elseif action.kind == "wait" then
    result.condition = action.condition
    result.progress = action.progress
    result.goal = action.goal
    if action.entity then
      result.entity = action.entity.valid and action.entity.name or "gone"
      result.status = action.entity.valid and entities.status(action.entity) or nil
    end
  end
  return result
end

function actions.current_summary(player)
  local action = storage.actions[player.index]
  return action and summary(player, action)
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
  local remaining = math.sqrt(common.distance_squared(position, action.target))
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
    local contents = entity and entities.contents(entity)
      or entities.inventory_contents(player.get_main_inventory())
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

function actions.on_tick(event)
  actions.ensure_storage()
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
end

function actions.on_player_mined_item(event)
  actions.ensure_storage()
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
end

function handlers.walk_to(params)
  local player = common.get_player(params)
  local dx = math.max(-100, math.min(100, common.required_number(params, "dx")))
  local dy = math.max(-100, math.min(100, common.required_number(params, "dy")))
  local start = player.position
  stop_player(player)
  storage.actions[player.index] = {
    kind = "walk_to",
    start = {x = start.x, y = start.y},
    target = {x = start.x + dx, y = start.y + dy},
    until_tick = game.tick + MAX_ACTION_TICKS,
  }
  return actions.current_summary(player)
end

function handlers.mine(params)
  local player = common.get_player(params)
  local position = common.position_from(player, params)
  local count = math.max(1, math.min(500, math.floor(common.required_number(params, "count"))))
  player.update_selected_entity(position)
  local target = player.selected
  if not target or not target.valid then
    common.fail("no mineable entity is selected at that position")
  end
  if not player.can_reach_entity(target) then
    common.fail("the target is outside mining reach")
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
  return actions.current_summary(player)
end

local WAIT_CONDITIONS = {crafts = true, items = true, handcraft = true}

function handlers.wait(params)
  local player = common.get_player(params)
  local condition = common.required_string(params, "condition")
  if not WAIT_CONDITIONS[condition] then
    common.fail("condition must be crafts, items, or handcraft")
  end
  local seconds = math.max(1, math.min(60, common.required_number(params, "seconds")))
  local action = {
    kind = "wait",
    condition = condition,
    until_tick = game.tick + math.floor(seconds * 60),
  }
  local targeted = (params.entity or "") ~= "" or (tonumber(params.id) or 0) ~= 0
  if condition == "crafts" or (condition == "items" and targeted) then
    if not targeted then
      common.fail("crafts needs an entity")
    end
    action.entity = entities.target(player, params)
  end
  if condition == "crafts" then
    local ok, finished = pcall(function() return action.entity.products_finished end)
    if not ok then
      common.fail(action.entity.name .. " does not count finished crafts; wait for items instead")
    end
    action.baseline = finished
  end
  if condition == "items" then
    action.item = ids.check(common.required_string(params, "item"), "item")
  end
  if condition ~= "handcraft" then
    action.goal = math.max(1, math.floor(common.required_number(params, "count")))
  end
  stop_player(player)
  storage.actions[player.index] = action
  tick_wait(player, action)
  return summary(player, action)
end

function handlers.status(params)
  local player = common.get_player(params)
  return actions.current_summary(player) or {done = true}
end

function handlers.stop(params)
  local player = common.get_player(params)
  local action = storage.actions[player.index]
  if not action then
    return {done = true}
  end
  if not action.done then
    finish(player, action, "stopped")
  end
  local result = summary(player, action)
  stop_player(player)
  return result
end

return actions
