local common = require("scripts.common")
local ids = require("scripts.ids")
local recipes = require("scripts.recipes")

local rounded = common.rounded
local handlers = {}

local FACINGS = {"north", "east", "south", "west"}
local FACING_TURNS = {north = 0, east = 1, south = 2, west = 3}
-- Each of a belt tile's two lanes holds 4 items.
local BELT_ITEMS_PER_TILE = 8
local INVENTORY_TYPES = {
  container = true,
  ["logistic-container"] = true,
  lab = true,
  ["ammo-turret"] = true,
}

-- Prototypes describe an entity facing north; each later facing is a quarter turn clockwise.
local function turned(x, y, turns)
  for _ = 1, turns do
    x, y = -y, x
  end
  return x, y
end

local function turned_side(direction, turns)
  return FACINGS[(FACING_TURNS[common.DIRECTION_NAMES[direction]] + turns) % 4 + 1]
end

local function facing_size(prototype, turns)
  if turns % 2 == 1 then
    return prototype.tile_height, prototype.tile_width
  end
  return prototype.tile_width, prototype.tile_height
end

-- An odd footprint is centred on a tile centre, an even one on a tile edge.
local function tile_axis(value, size)
  local offset = size % 2 == 1 and 0.5 or 0
  return math.floor(value + offset) + 0.5 - offset
end

-- Tiles whose centres lie within radius of the entity centre along one axis.
local function tiles_within(radius, size)
  if size % 2 == 1 then
    return 2 * math.floor(radius) + 1
  end
  return 2 * math.floor(radius + 0.5)
end

-- The footprint side a tile lies beyond, or nil for a tile inside it.
local function side_of(dx, dy, width, height)
  if dy < -height / 2 then return "north" end
  if dy > height / 2 then return "south" end
  if dx > width / 2 then return "east" end
  if dx < -width / 2 then return "west" end
  return nil
end

-- The tile outside the footprint that a north-facing vector lands on.
local function port(vector, width, height, turns)
  if not vector then
    return nil
  end
  local x, y = turned(vector[1], vector[2], turns)
  local dx, dy = tile_axis(x, width), tile_axis(y, height)
  local side = side_of(dx, dy, width, height)
  return side and {dx = dx, dy = dy, side = side}
end

-- Each connection's tile is the outside tile a connecting pipe goes on.
local function fluid_connections(prototype, turns)
  local result = {}
  for _, fluidbox in pairs(prototype.fluidbox_prototypes) do
    for _, connection in pairs(fluidbox.pipe_connections) do
      if connection.connection_type ~= "linked" then
        local x, y = turned(connection.positions[1].x, connection.positions[1].y, turns)
        local side = turned_side(connection.direction, turns)
        local step = common.DIRECTION_STEPS[defines.direction[side]]
        table.insert(result, {
          dx = rounded(x + step.x),
          dy = rounded(y + step.y),
          side = side,
          flow = connection.flow_direction,
          fluid = fluidbox.filter and fluidbox.filter.name,
          underground_max = connection.max_underground_distance,
        })
      end
    end
  end
  return result
end

local function facing(prototype, turns)
  local width, height = facing_size(prototype, turns)
  local entry = {
    pickup = port(prototype.inserter_pickup_position, width, height, turns),
    drop = port(prototype.inserter_drop_position, width, height, turns),
    item_out = port(prototype.vector_to_place_result, width, height, turns),
  }
  if prototype.belt_speed then
    entry.items_move = FACINGS[turns + 1]
  end
  local fluids = fluid_connections(prototype, turns)
  if #fluids > 0 then
    entry.fluids = fluids
  end
  if width ~= prototype.tile_width then
    entry.size = {w = width, h = height}
  end
  return entry
end

local function item_access(prototype)
  if prototype.belt_speed or prototype.crafting_categories or INVENTORY_TYPES[prototype.type] then
    return "any_side"
  end
  if prototype.burner_prototype then
    return "fuel_any_side"
  end
  return "none"
end

local function power(prototype)
  local production = prototype.get_max_energy_production()
  if production > 0 then
    return {produces_kw = rounded(production * 60 / 1000)}
  end
  local source, kw = recipes.power_needs(prototype)
  -- A void source such as the offshore pump's still states an energy_usage.
  if source == "none" then
    return {source = source}
  end
  -- Boilers and inserters state their usage in other fields than energy_usage.
  local maximum = prototype.get_max_energy_usage()
  if not kw and maximum > 0 then
    kw = rounded(maximum * 60 / 1000)
  end
  return {source = source, kw = kw}
end

local function by_direction(prototype)
  if not prototype.supports_direction then
    return nil
  end
  local result = {}
  for index, name in pairs(FACINGS) do
    local entry = facing(prototype, index - 1)
    if next(entry) then
      result[name] = entry
    end
  end
  return next(result) and result
end

-- "fluids_only" when facing moves pipe connections and nothing else.
local function directional(facings)
  if not facings then
    return false
  end
  for _, entry in pairs(facings) do
    for field in pairs(entry) do
      if field ~= "fluids" then
        return true
      end
    end
  end
  return "fluids_only"
end

local function entity_prototype(name)
  name = ids.check(name, "entity", "item")
  local prototype = prototypes.entity[name] or prototypes.item[name].place_result
  if not prototype then
    common.fail(name .. " places no entity")
  end
  return prototype
end

function handlers.entity_info(params)
  local prototype = entity_prototype(common.required_string(params, "entity"))
  local placed_by = (prototype.items_to_place_this or {})[1]
  local info = {
    entity = prototype.name,
    type = prototype.type,
    item = placed_by and placed_by.name,
    size = {w = prototype.tile_width, h = prototype.tile_height},
    items = item_access(prototype),
    power = power(prototype),
    by_direction = by_direction(prototype),
  }
  info.directional = directional(info.by_direction)
  local fluids = fluid_connections(prototype, 0)
  if #fluids == 0 then
    info.fluids = "none"
  elseif not info.directional then
    info.fluids = fluids
  end
  if prototype.crafting_categories then
    info.crafting_speed = rounded(prototype.get_crafting_speed())
  end
  if prototype.mining_drill_radius then
    info.mining_speed = rounded(prototype.mining_speed)
    info.mining_area = {
      w = tiles_within(prototype.mining_drill_radius, prototype.tile_width),
      h = tiles_within(prototype.mining_drill_radius, prototype.tile_height),
    }
  end
  if prototype.lab_inputs then
    info.researching_speed = rounded(prototype.get_researching_speed())
  end
  if prototype.belt_speed then
    info.belt_items_per_second = rounded(prototype.belt_speed * 60 * BELT_ITEMS_PER_TILE)
    info.underground_max = prototype.max_underground_distance
  end
  if prototype.type == "container" or prototype.type == "logistic-container" then
    info.slots = prototype.get_inventory_size(defines.inventory.chest)
  end
  if prototype.type == "offshore-pump" or prototype.type == "pump" then
    info.fluid_per_second = rounded(prototype.get_pumping_speed() * 60)
  end
  if prototype.type == "electric-pole" then
    local reach = prototype.get_supply_area_distance()
    info.supply_area = {w = 2 * reach, h = 2 * reach}
    info.wire_reach = rounded(prototype.get_max_wire_distance())
  end
  return info
end

local info = {handlers = handlers}

-- Pickup, drop, and item_out tiles of a prototype facing direction, as api_entity_info
-- lists them.
function info.ports(prototype, direction)
  return facing(prototype, FACING_TURNS[common.DIRECTION_NAMES[direction]])
end

return info
