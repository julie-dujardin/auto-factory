-- Where to build: footprints, positions relative to existing entities, and the spots
-- where an inserter or electric pole connects the entities it is meant to.
local common = require("scripts.common")
local entities = require("scripts.entities")
local info = require("scripts.info")

local layout = {}

local CARDINALS = {
  defines.direction.north,
  defines.direction.east,
  defines.direction.south,
  defines.direction.west,
}

function layout.footprint(entity, direction)
  if not entity then
    return 1, 1
  end
  if direction == defines.direction.east or direction == defines.direction.west then
    return entity.tile_height, entity.tile_width
  end
  return entity.tile_width, entity.tile_height
end

-- Where the engine centres a footprint of this size built at value.
function layout.snap(value, size)
  if size % 2 == 1 then
    return math.floor(value) + 0.5
  end
  return math.floor(value + 0.5)
end

function layout.area(position, width, height)
  return {
    left_top = {x = position.x - width / 2, y = position.y - height / 2},
    right_bottom = {x = position.x + width / 2, y = position.y + height / 2},
  }
end

local function entity_area(entity)
  return layout.area(entity.position, entity.tile_width, entity.tile_height)
end

function layout.overlaps(a, b)
  return a.left_top.x < b.right_bottom.x and b.left_top.x < a.right_bottom.x
    and a.left_top.y < b.right_bottom.y and b.left_top.y < a.right_bottom.y
end

local function inside(areas, point)
  for _, area in pairs(areas) do
    if point.x > area.left_top.x and point.x < area.right_bottom.x
      and point.y > area.left_top.y and point.y < area.right_bottom.y then
      return true
    end
  end
  return false
end

local function tile_of(position)
  return {x = math.floor(position.x) + 0.5, y = math.floor(position.y) + 0.5}
end

-- The straight run of same-named belts facing the same way through belt, upstream first.
local function belt_run(belt)
  local step = common.DIRECTION_STEPS[belt.direction]
  local function neighbour(from, sign)
    local other = belt.surface.find_entity(belt.name, {
      x = from.position.x + sign * step.x,
      y = from.position.y + sign * step.y,
    })
    return other and other.direction == belt.direction and other or nil
  end
  local first = belt
  while neighbour(first, -1) do
    first = neighbour(first, -1)
  end
  local run = {}
  local current = first
  while current do
    table.insert(run, current)
    current = neighbour(current, 1)
  end
  return run
end

local function port_tile(anchor, at)
  if at == "item_out" then
    if anchor.type ~= "mining-drill" then
      common.fail("item_out needs a mining drill anchor, not " .. anchor.name)
    end
    return tile_of(anchor.drop_position)
  end
  if at == "pickup" or at == "drop" then
    if anchor.type ~= "inserter" then
      common.fail(at .. " needs an inserter anchor, not " .. anchor.name)
    end
    return tile_of(at == "pickup" and anchor.pickup_position or anchor.drop_position)
  end
  if anchor.type ~= "transport-belt" then
    common.fail(at .. " needs a transport belt anchor, not " .. anchor.name)
  end
  local run = belt_run(anchor)
  local step = common.DIRECTION_STEPS[anchor.direction]
  if at == "ahead" then
    local last = run[#run].position
    return {x = last.x + step.x, y = last.y + step.y}
  end
  local first = run[1].position
  return {x = first.x - step.x, y = first.y - step.y}
end

-- The centre of a footprint flush against side of area, along tiles from its north or
-- west end.
local function beside(area, side, along, width, height)
  local left_top, right_bottom = area.left_top, area.right_bottom
  if side == "east" then
    return {x = right_bottom.x + width / 2, y = left_top.y + along + height / 2}
  elseif side == "west" then
    return {x = left_top.x - width / 2, y = left_top.y + along + height / 2}
  elseif side == "south" then
    return {x = left_top.x + along + width / 2, y = right_bottom.y + height / 2}
  end
  return {x = left_top.x + along + width / 2, y = left_top.y - height / 2}
end

local function clamp(value, low, high)
  return math.max(low, math.min(high, value))
end

-- The centre of a footprint covering tile from its edge nearest area, shifted along that
-- edge to be as centred on area as it can.
local function covering(area, tile, width, height)
  local left_top, right_bottom = area.left_top, area.right_bottom
  local middle = {x = (left_top.x + right_bottom.x) / 2, y = (left_top.y + right_bottom.y) / 2}
  if tile.x > right_bottom.x or tile.x < left_top.x then
    local x = tile.x > right_bottom.x and tile.x - 0.5 + width / 2 or tile.x + 0.5 - width / 2
    local top = clamp(math.floor(middle.y - height / 2 + 0.5), tile.y + 0.5 - height, tile.y - 0.5)
    return {x = x, y = top + height / 2}
  end
  if tile.y > right_bottom.y or tile.y < left_top.y then
    local y = tile.y > right_bottom.y and tile.y - 0.5 + height / 2 or tile.y + 0.5 - height / 2
    local left = clamp(math.floor(middle.x - width / 2 + 0.5), tile.x + 0.5 - width, tile.x - 0.5)
    return {x = left + width / 2, y = y}
  end
  common.fail("that tile is inside the anchor")
end

local SIDES = {north = true, east = true, south = true, west = true}

-- The first entity's centre from api_place's anchor, at, along, and dx/dy, and for an
-- offset the position asked for before snapping to the grid.
function layout.start(player, params, width, height)
  local at = params.at or "offset"
  local id = math.floor(tonumber(params.anchor) or 0)
  if at == "offset" then
    local origin = id == 0 and common.origin(player) or entities.by_id(id).position
    local requested = {
      x = origin.x + common.required_number(params, "dx"),
      y = origin.y + common.required_number(params, "dy"),
    }
    return {x = layout.snap(requested.x, width), y = layout.snap(requested.y, height)}, requested
  end
  if id == 0 then
    common.fail("at " .. at .. " needs an anchor")
  end
  local anchor = entities.by_id(id)
  if SIDES[at] then
    local along = math.floor(tonumber(params.along) or 0)
    return beside(entity_area(anchor), at, along, width, height)
  end
  return covering(entity_area(anchor), port_tile(anchor, at), width, height)
end

-- Areas an inserter can reach into: a transport belt's whole straight run, else the
-- entity's footprint.
local function reachable_areas(entity)
  if entity.type ~= "transport-belt" then
    return {entity_area(entity)}
  end
  local areas = {}
  for _, belt in pairs(belt_run(entity)) do
    table.insert(areas, entity_area(belt))
  end
  return areas
end

local function gap(a, b)
  return math.max(0, a.left_top.x - b.right_bottom.x, b.left_top.x - a.right_bottom.x),
    math.max(0, a.left_top.y - b.right_bottom.y, b.left_top.y - a.right_bottom.y)
end

-- Spots, nearest the middle of source and target first, where an inserter of prototype
-- takes from source and drops into target.
function layout.inserter_spots(prototype, source, target)
  local from, into = reachable_areas(source), reachable_areas(target)
  local middle = {
    x = (source.position.x + target.position.x) / 2,
    y = (source.position.y + target.position.y) / 2,
  }
  local spots = {}
  for _, direction in pairs(CARDINALS) do
    local ports = info.ports(prototype, direction)
    for _, area in pairs(into) do
      for x = area.left_top.x + 0.5, area.right_bottom.x, 1 do
        for y = area.left_top.y + 0.5, area.right_bottom.y, 1 do
          local position = {x = x - ports.drop.dx, y = y - ports.drop.dy}
          local pickup = {x = position.x + ports.pickup.dx, y = position.y + ports.pickup.dy}
          if inside(from, pickup) and not inside(from, position) and not inside(into, position) then
            table.insert(spots, {
              position = position,
              direction = direction,
              distance = common.distance_squared(position, middle),
            })
          end
        end
      end
    end
  end
  if #spots == 0 then
    local north = info.ports(prototype, defines.direction.north)
    local apart_x, apart_y = gap(entity_area(source), entity_area(target))
    common.fail(
      "no spot lets a " .. prototype.name .. " take from " .. entities.label(source)
        .. " and drop into " .. entities.label(target) .. ": it picks up "
        .. math.abs(north.pickup.dy) .. " tile(s) and drops " .. math.abs(north.drop.dy)
        .. " tile(s) away in a straight line, and they are " .. apart_x
        .. " tiles apart east-west and " .. apart_y .. " north-south"
    )
  end
  table.sort(spots, function(a, b) return a.distance < b.distance end)
  return spots
end

-- Footprint centres of this size strictly between low and high along one axis.
local function centres(low, high, size)
  local result = {}
  local offset = size % 2 == 1 and 0.5 or 0
  for value = math.floor(low) + offset, high, 1 do
    if value > low and value < high then
      table.insert(result, value)
    end
  end
  return result
end

-- Spots where a pole of prototype covers every target with its supply area, those in
-- wire reach of an existing pole first, then nearest the targets' middle.
function layout.pole_spots(prototype, targets)
  local reach = prototype.get_supply_area_distance()
  local wire = prototype.get_max_wire_distance()
  local low = {x = -math.huge, y = -math.huge}
  local high = {x = math.huge, y = math.huge}
  local middle = {x = 0, y = 0}
  for _, target in pairs(targets) do
    local area = entity_area(target)
    low.x = math.max(low.x, area.left_top.x - reach)
    low.y = math.max(low.y, area.left_top.y - reach)
    high.x = math.min(high.x, area.right_bottom.x + reach)
    high.y = math.min(high.y, area.right_bottom.y + reach)
    middle.x = middle.x + target.position.x / #targets
    middle.y = middle.y + target.position.y / #targets
  end
  local xs = centres(low.x, high.x, prototype.tile_width)
  local ys = centres(low.y, high.y, prototype.tile_height)
  if #xs == 0 or #ys == 0 then
    common.fail(
      "no single " .. prototype.name .. " covers all of them: its supply area is "
        .. 2 * reach .. " tiles across"
    )
  end
  local poles = targets[1].surface.find_entities_filtered {
    type = "electric-pole",
    area = {
      left_top = {x = low.x - wire, y = low.y - wire},
      right_bottom = {x = high.x + wire, y = high.y + wire},
    },
  }
  local spots = {}
  for _, x in pairs(xs) do
    for _, y in pairs(ys) do
      local position = {x = x, y = y}
      local wired = false
      for _, pole in pairs(poles) do
        local limit = math.min(wire, pole.prototype.get_max_wire_distance(pole.quality))
        if common.distance_squared(position, pole.position) <= limit * limit then
          wired = true
          break
        end
      end
      table.insert(spots, {
        position = position,
        direction = defines.direction.north,
        wired = wired,
        distance = common.distance_squared(position, middle),
      })
    end
  end
  table.sort(spots, function(a, b)
    if a.wired ~= b.wired then
      return a.wired
    end
    return a.distance < b.distance
  end)
  return spots
end

return layout
