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

-- Per side (1 left, 2 right): item counts, line length, and how many items moved since
-- the recent sample, nil without one.
local function measure(entity)
  local before = baseline(entity.unit_number)
  local sides = {}
  for side = 1, 2 do
    sides[side] = {counts = {}, moving = before and 0, length = 0}
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
  return sides
end

local function most_common(counts)
  local best, best_count = nil, 0
  for name, count in pairs(counts) do
    if count > best_count then
      best, best_count = name, count
    end
  end
  return best
end

-- Each lane's most common item and, when measured against a recent sample, its flow in
-- items/s: the density of items that moved since that sample times the belt speed.
local function lanes(sides, items_per_second)
  local result = {}
  for side, key in ipairs({"left", "right"}) do
    local item = most_common(sides[side].counts)
    if item then
      result[key] = {item = item}
      if sides[side].moving and sides[side].length > 0 then
        result[key].per_second = common.rounded(
          sides[side].moving / sides[side].length * items_per_second
        )
      end
    end
  end
  return next(result) and result or nil
end

function belts.lanes(entity)
  if not BELT_TYPES[entity.type] then
    return nil
  end
  -- A splitter carries two belts side by side.
  local paths = entity.type == "splitter" and 2 or 1
  return lanes(measure(entity), entity.prototype.belt_speed * 60 * paths)
end

local function tile_key(x, y)
  return math.floor(x) .. "," .. math.floor(y)
end

-- Transport belts as one entry per straight run: consecutive tiles with the same name
-- and direction, split where a lane's item changes. Each entry comes with the squared
-- distance from origin to the run's nearest belt.
function belts.runs(transport_belts, origin)
  local at = {}
  local measured = {}
  for _, belt in pairs(transport_belts) do
    at[tile_key(belt.position.x, belt.position.y)] = belt
    measured[belt.unit_number] = measure(belt)
  end

  local function neighbour(belt, sign)
    local step = common.DIRECTION_STEPS[belt.direction]
    local other = at[tile_key(belt.position.x + sign * step.x, belt.position.y + sign * step.y)]
    if other and other.name == belt.name and other.direction == belt.direction then
      return other
    end
    return nil
  end

  local function start(head)
    local run = {head = head, length = 0, items = {}, distance = math.huge, sides = {}}
    for side = 1, 2 do
      run.sides[side] = {counts = {}, moving = 0, length = 0}
    end
    return run
  end

  local function fits(run, belt)
    for side = 1, 2 do
      local item = most_common(measured[belt.unit_number][side].counts)
      if item and run.items[side] and item ~= run.items[side] then
        return false
      end
    end
    return true
  end

  local function extend(run, belt)
    run.length = run.length + 1
    run.distance = math.min(run.distance, common.distance_squared(origin, belt.position))
    for side = 1, 2 do
      local into, from = run.sides[side], measured[belt.unit_number][side]
      for name, count in pairs(from.counts) do
        into.counts[name] = (into.counts[name] or 0) + count
      end
      into.moving = into.moving and from.moving and into.moving + from.moving
      into.length = into.length + from.length
      run.items[side] = run.items[side] or most_common(from.counts)
    end
  end

  local results = {}
  local function finish(run)
    local head = run.head
    table.insert(results, {
      distance = run.distance,
      entry = {
        name = head.name,
        type = head.type,
        position = common.offset_from(origin, head.position),
        direction = common.DIRECTION_NAMES[head.direction],
        length = run.length,
        lanes = lanes(run.sides, head.prototype.belt_speed * 60),
      },
    })
  end

  -- A straight run has no loop, so walking downstream from each head covers every belt.
  for _, head in pairs(transport_belts) do
    if not neighbour(head, -1) then
      local run = start(head)
      local belt = head
      while belt do
        if not fits(run, belt) then
          finish(run)
          run = start(belt)
        end
        extend(run, belt)
        belt = neighbour(belt, 1)
      end
      finish(run)
    end
  end
  return results
end

return belts
