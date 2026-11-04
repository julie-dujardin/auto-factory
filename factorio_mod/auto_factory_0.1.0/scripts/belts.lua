local common = require("scripts.common")
local ids = require("scripts.ids")

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
  return best, best_count
end

-- Each lane's most common item, its count and, when measured against a recent sample,
-- its flow in items/s: the density of items that moved since that sample times the belt
-- speed.
local function lanes(sides, items_per_second)
  local result = {}
  for side, key in ipairs({"left", "right"}) do
    local item, count = most_common(sides[side].counts)
    if item then
      result[key] = {item = item, count = count}
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


-- Transport and underground belts are listed only as parts of lines.
belts.LINE_TYPES = {["transport-belt"] = true, ["underground-belt"] = true}

local function is_underground(entity, kind)
  return entity.type == "underground-belt" and entity.belt_to_ground_type == kind
end

-- Where entity sends its items: the belt connectable ahead, or an entrance's exit.
local function output(entity)
  if is_underground(entity, "input") then
    return entity.underground_belt_neighbour
  end
  return entity.belt_neighbours.outputs[1]
end

-- Whether items from from carry on along to's line, both lanes keeping their side: fed
-- from behind or around a curve. Anything else feeding a belt sideloads it.
local function carries_on(from, to)
  if to.type == "transport-belt" then
    return to.direction == from.direction or to.belt_shape ~= "straight"
  end
  return to.type == "underground-belt" and to.direction == from.direction
end

-- The belt connectable whose items carry on into entity, if any.
local function feeder(entity)
  if is_underground(entity, "output") then
    return entity.underground_belt_neighbour
  end
  for _, input in pairs(entity.belt_neighbours.inputs) do
    if carries_on(input, entity) then
      return input
    end
  end
  return nil
end

-- Whether to is the next tile of from's straight run.
local function straight_on(from, to)
  return from.type == "transport-belt" and to.type == "transport-belt"
    and from.name == to.name and from.direction == to.direction
end

-- How far position lies to entity's left, facing its direction; negative is right.
local function leftward(entity, position)
  local step = common.DIRECTION_STEPS[entity.direction]
  return (position.x - entity.position.x) * step.y - (position.y - entity.position.y) * step.x
end

local function lane_of(entity, position)
  return leftward(entity, position) > 0 and "left lane" or "right lane"
end

local UNFACED_TYPES = {"character", "item-entity", "resource"}

-- What a belt ending before position points at there.
local function faced(surface, position)
  for _, other in pairs(surface.find_entities_filtered {
    position = position,
    type = UNFACED_TYPES,
    invert = true,
  }) do
    if ids.selectable(other.prototype) then
      return other
    end
  end
  return nil
end

-- Transport and underground belts as lines: chains through turns and underground pairs,
-- upstream first, split where a lane's item changes. Each comes as its entry with the
-- squared distance from centre to its nearest belt. Also returns where each splitter's
-- outputs go, by unit number. scan holds every entity found; id_of gives an entity's id.
function belts.lines(scan, centre, origin, id_of)
  local scanned, chain, splitters = {}, {}, {}
  for _, entity in pairs(scan) do
    if entity.unit_number then
      scanned[entity.unit_number] = true
    end
    if belts.LINE_TYPES[entity.type] then
      table.insert(chain, entity)
    elseif entity.type == "splitter" then
      table.insert(splitters, entity)
    end
  end

  local function label(entity)
    local id = id_of(entity)
    return id and entity.name .. " #" .. id or entity.name
  end

  local function spot(position)
    local offset = common.offset_from(origin, position)
    return offset.dx .. "," .. offset.dy
  end

  local onward, fed, measured = {}, {}, {}
  for _, belt in pairs(chain) do
    local ahead = output(belt)
    if ahead and belts.LINE_TYPES[ahead.type] and scanned[ahead.unit_number]
      and carries_on(belt, ahead) then
      onward[belt.unit_number] = ahead
      fed[ahead.unit_number] = true
    end
    measured[belt.unit_number] = measure(belt)
  end

  local function start(head)
    local line = {head = head, members = {}, items = {}, distance = math.huge, sides = {}}
    for side = 1, 2 do
      line.sides[side] = {counts = {}, moving = 0, length = 0}
    end
    return line
  end

  -- An exit stays in its entrance's line.
  local function fits(line, belt)
    if is_underground(belt, "output") then
      return true
    end
    for side = 1, 2 do
      local item = most_common(measured[belt.unit_number][side].counts)
      if item and line.items[side] and item ~= line.items[side] then
        return false
      end
    end
    return true
  end

  local function extend(line, belt)
    table.insert(line.members, belt)
    line.distance = math.min(line.distance, common.distance_squared(centre, belt.position))
    for side = 1, 2 do
      local into, from = line.sides[side], measured[belt.unit_number][side]
      for name, count in pairs(from.counts) do
        into.counts[name] = (into.counts[name] or 0) + count
      end
      into.moving = into.moving and from.moving and into.moving + from.moving
      into.length = into.length + from.length
      line.items[side] = line.items[side] or most_common(from.counts)
    end
  end

  local lines, walked = {}, {}
  local function walk(head)
    local line = start(head)
    local belt = head
    while belt do
      if not fits(line, belt) then
        table.insert(lines, line)
        line = start(belt)
      end
      extend(line, belt)
      walked[belt.unit_number] = true
      belt = onward[belt.unit_number]
      if belt and walked[belt.unit_number] then
        belt = nil
      end
    end
    table.insert(lines, line)
  end
  for _, belt in pairs(chain) do
    if not fed[belt.unit_number] then
      walk(belt)
    end
  end
  -- What is left are loops, entered anywhere but at an exit.
  for _, belt in pairs(chain) do
    if not walked[belt.unit_number] and not is_underground(belt, "output") then
      walk(belt)
    end
  end

  -- Each line's parts: straight runs of same-named belts, and underground pairs.
  local part_of = {}
  for _, line in pairs(lines) do
    line.parts = {}
    local part
    for _, belt in ipairs(line.members) do
      local joins
      if belt.type == "underground-belt" then
        joins = part and part.underground and is_underground(part.last, "input")
      else
        joins = part and not part.underground and straight_on(part.last, belt)
      end
      if not joins then
        part = {first = belt, underground = belt.type == "underground-belt"}
        table.insert(line.parts, part)
      end
      part.last = belt
      part_of[belt.unit_number] = part
    end
  end

  -- An entity by its line part's first id, with its own position when not that tile.
  local function where(entity)
    local part = part_of[entity.unit_number]
    if not part or part.first == entity then
      return label(entity)
    end
    return label(part.first) .. " at " .. spot(entity.position)
  end

  -- Where from's items go when it feeds to, or with nothing to feed, what it points at
  -- on the tile ahead.
  local function target(from, to, ahead)
    if not to then
      local other = ahead and faced(from.surface, ahead)
      return other and "nothing, faces " .. where(other) or "nothing"
    end
    if not scanned[to.unit_number] then
      return "beyond scan"
    end
    if not part_of[to.unit_number] or carries_on(from, to) then
      return where(to)
    end
    return where(to) .. ", " .. lane_of(to, from.position)
  end

  local function part_text(line, part)
    local first, last = part.first, part.last
    local direction = common.DIRECTION_NAMES[first.direction]
    local text
    if not part.underground then
      local before, after = feeder(first), output(last)
      local up = first == line.head and before and not scanned[before.unit_number]
        and straight_on(before, first)
      local down = last == line.members[#line.members] and after
        and not scanned[after.unit_number] and straight_on(last, after)
      local span = (up and "beyond scan" or spot(first.position)) .. " → "
        .. (down and "beyond scan" or spot(last.position))
      if first == last and not (up or down) then
        span = spot(first.position)
      elseif up and down then
        local offset = common.offset_from(origin, first.position)
        local across = common.DIRECTION_STEPS[first.direction].x ~= 0
          and "dy=" .. offset.dy or "dx=" .. offset.dx
        span = span .. ", along " .. across
      end
      text = "#" .. id_of(first) .. " " .. direction .. " " .. span
    else
      local entrance = is_underground(first, "input") and first or nil
      local exit = is_underground(last, "output") and last or nil
      local pair = (entrance or exit).underground_belt_neighbour
      local kind = " underground " .. direction .. " "
      if entrance and exit then
        text = "#" .. id_of(entrance) .. kind .. spot(entrance.position)
          .. " → #" .. id_of(exit) .. " " .. spot(exit.position)
      elseif entrance then
        text = "#" .. id_of(entrance) .. kind .. spot(entrance.position)
          .. (pair and " → beyond scan" or ", no exit")
      elseif pair then
        text = "underground " .. direction .. " beyond scan → #" .. id_of(exit) .. " "
          .. spot(exit.position)
      else
        text = "#" .. id_of(exit) .. kind .. spot(exit.position) .. ", no entrance"
      end
    end
    if first.prototype.belt_speed ~= line.tier.prototype.belt_speed then
      text = text .. " " .. first.name
    end
    return text
  end

  local results = {}
  for _, line in pairs(lines) do
    -- Names the line's tier: its first transport belt when it has one.
    line.tier = line.head
    for _, belt in ipairs(line.members) do
      if belt.type == "transport-belt" then
        line.tier = belt
        break
      end
    end
    local path = {}
    for _, part in ipairs(line.parts) do
      table.insert(path, part_text(line, part))
    end
    -- Belts outside the scan feeding the line; the path shows a straight run carrying on.
    local from = {}
    for _, belt in ipairs(line.members) do
      for _, input in pairs(belt.belt_neighbours.inputs) do
        if not scanned[input.unit_number] then
          if not carries_on(input, belt) then
            table.insert(from, "beyond scan, sideloads at " .. spot(belt.position) .. ", "
              .. lane_of(belt, input.position))
          elseif not straight_on(input, belt) then
            table.insert(from, "beyond scan")
          end
        end
      end
    end
    local tail = line.members[#line.members]
    local step = common.DIRECTION_STEPS[tail.direction]
    local ahead = not is_underground(tail, "input")
      and {x = tail.position.x + step.x, y = tail.position.y + step.y} or nil
    table.insert(results, {
      distance = line.distance,
      entry = {
        type = "belt-line",
        name = line.tier.name,
        path = path,
        lanes = lanes(line.sides, line.tier.prototype.belt_speed * 60),
        from = #from > 0 and from or nil,
        into = target(tail, output(tail), ahead),
      },
    })
  end

  -- Each splitter output by side, seen facing the splitter's direction.
  local outputs = {}
  for _, splitter in pairs(splitters) do
    local sides = {}
    for _, other in pairs(splitter.belt_neighbours.outputs) do
      local offset = leftward(splitter, other.position)
      local text = target(splitter, other)
      if offset >= 0 then
        sides.left = text
      end
      if offset <= 0 then
        sides.right = text
      end
    end
    local step = common.DIRECTION_STEPS[splitter.direction]
    for side, sign in pairs({left = 1, right = -1}) do
      sides[side] = sides[side] or target(splitter, nil, {
        x = splitter.position.x + step.x + sign * step.y / 2,
        y = splitter.position.y + step.y - sign * step.x / 2,
      })
    end
    outputs[splitter.unit_number] = sides
  end
  return results, outputs
end

return belts
