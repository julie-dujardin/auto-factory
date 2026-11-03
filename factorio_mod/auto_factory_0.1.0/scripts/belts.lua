local common = require("scripts.common")

local belts = {}

local BELT_TYPES = {
  ["lane-splitter"] = true,
  ["linked-belt"] = true,
  ["loader"] = true,
  ["loader-1x1"] = true,
  ["splitter"] = true,
  ["transport-belt"] = true,
  ["underground-belt"] = true,
}

-- Ticks after which a sample no longer describes the belt's flow.
local SAMPLE_WINDOW = 120

-- Item positions per belt, kept for the tick of the latest call and the one before.
-- They only feed the next response, so they live outside storage.
local current = {tick = nil, belts = {}}
local previous = {tick = nil, belts = {}}

local function baseline(unit_number)
  if current.tick ~= game.tick then
    previous = current
    current = {tick = game.tick, belts = {}}
  end
  if previous.tick and game.tick - previous.tick <= SAMPLE_WINDOW then
    return previous.belts[unit_number]
  end
  return nil
end

-- Each lane's most common item and, when a recent sample exists, its flow in items/s:
-- the density of items that moved since that sample times the belt speed.
function belts.lanes(entity)
  if not BELT_TYPES[entity.type] then
    return nil
  end
  local before = baseline(entity.unit_number)
  local sides = {}
  for side = 1, 2 do
    sides[side] = {counts = {}, moving = 0, length = 0}
  end
  local sample = {}
  -- Odd transport line indices are left lanes and even ones right (defines.transport_line).
  for index = 1, entity.get_max_transport_line_index() do
    local line = entity.get_transport_line(index)
    local side = sides[2 - index % 2]
    local positions = {}
    side.length = side.length + line.line_length
    for _, item in pairs(line.get_detailed_contents()) do
      local name, count = item.stack.name, item.stack.count
      side.counts[name] = (side.counts[name] or 0) + count
      positions[item.unique_id] = item.position
      if before and before[index][item.unique_id] ~= item.position then
        side.moving = side.moving + count
      end
    end
    sample[index] = positions
  end
  current.belts[entity.unit_number] = sample

  -- A splitter carries two belts side by side.
  local paths = entity.type == "splitter" and 2 or 1
  local items_per_second = entity.prototype.belt_speed * 60 * paths
  local lanes = {}
  for side, key in ipairs({"left", "right"}) do
    local best_count = 0
    for name, count in pairs(sides[side].counts) do
      if count > best_count then
        lanes[key] = {item = name}
        best_count = count
      end
    end
    if lanes[key] and before and sides[side].length > 0 then
      lanes[key].per_second = common.rounded(
        sides[side].moving / sides[side].length * items_per_second
      )
    end
  end
  return next(lanes) and lanes or nil
end

return belts
