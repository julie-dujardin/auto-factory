local belts = require("scripts.belts")
local common = require("scripts.common")
local ids = require("scripts.ids")

local entities = {}

local STATUS_NAMES = {}
for name, value in pairs(defines.entity_status) do
  STATUS_NAMES[value] = name
end

function entities.inventory_contents(inventory)
  local result = {}
  if not inventory or not inventory.valid then
    return result
  end
  for _, stack in pairs(inventory.get_contents()) do
    result[stack.name] = (result[stack.name] or 0) + stack.count
  end
  return result
end

function entities.contents(entity)
  local result = {}
  local maximum = entity.get_max_inventory_index()
  for index = 1, maximum do
    local inventory = entity.get_inventory(index)
    if inventory and inventory.valid then
      for name, count in pairs(entities.inventory_contents(inventory)) do
        result[name] = (result[name] or 0) + count
      end
    end
  end
  return result
end

function entities.status(entity)
  local ok, status = pcall(function() return entity.status end)
  if ok and status then
    return STATUS_NAMES[status] or status
  end
  return nil
end

function entities.amount(entity)
  if entity.type == "resource" then
    return entity.amount
  end
  local total = 0
  for _, count in pairs(entities.contents(entity)) do
    total = total + count
  end
  return total
end

local FIND_RADIUS = 0.8
local NEARBY_RADIUS = 32
local NEARBY_LISTED = 5

function entities.find(player, name, position)
  local surface = player.surface
  ids.check(name, "entity")
  local candidates = surface.find_entities_filtered {
    position = position,
    radius = FIND_RADIUS,
    name = name,
  }
  -- Large footprints reach further than FIND_RADIUS from their centre.
  if #candidates == 0 then
    candidates = surface.find_entities_filtered {position = position, name = name}
  end
  if #candidates > 0 then
    return common.nearest_first(candidates, position)[1]
  end
  local requested = common.offset_text(player.position, position)
  local nearby = common.nearest_first(
    surface.find_entities_filtered {position = position, radius = NEARBY_RADIUS, name = name},
    position
  )
  if #nearby == 0 then
    common.fail(
      "no " .. name .. " within " .. NEARBY_RADIUS .. " tiles of " .. requested
        .. "; api_find searches further"
    )
  end
  local offsets = {}
  for index = 1, math.min(NEARBY_LISTED, #nearby) do
    table.insert(offsets, common.offset_text(player.position, nearby[index].position))
  end
  common.fail("no " .. name .. " at " .. requested .. "; nearest: " .. table.concat(offsets, ", "))
end

local function underground_pair(entity)
  if entity.type == "underground-belt" then
    return entity.underground_belt_neighbour
  end
  for _, connection in pairs(entity.get_fluid_box_pipe_connections(1) or {}) do
    if connection.connection_type == "underground" then
      return connection.target
    end
  end
  return nil
end

-- Power switches merge sub networks, so the parent network is the one sharing power.
local function network_power(pole)
  local network = pole.electric_network
  if not network then
    return nil
  end
  local flow = network.parent_network.flow_last_tick
  return {
    available_kw = common.rounded(flow.maximum_production * 60 / 1000),
    demand_kw = common.rounded(flow.maximum_consumption * 60 / 1000),
  }
end

local function supply_area(pole, origin)
  local reach = pole.prototype.get_supply_area_distance(pole.quality)
  local position = pole.position
  return {
    left_top = common.offset_from(origin, {x = position.x - reach, y = position.y - reach}),
    right_bottom = common.offset_from(origin, {x = position.x + reach, y = position.y + reach}),
  }
end

function entities.entry(entity, origin)
  local entry = {
    name = entity.name,
    type = entity.type,
    position = common.offset_from(origin, entity.position),
  }
  if entity.supports_direction then
    entry.direction = common.DIRECTION_NAMES[entity.direction]
  end
  if entity.type == "resource" then
    entry.amount = entity.amount
  end
  if entity.type == "underground-belt" then
    entry.underground = entity.belt_to_ground_type
  end
  if entity.type == "underground-belt" or entity.type == "pipe-to-ground" then
    local pair = underground_pair(entity)
    entry.pair = pair and common.offset_from(origin, pair.position) or "unconnected"
  end
  if entity.type == "electric-pole" then
    entry.supply_area = supply_area(entity, origin)
    entry.power = network_power(entity)
  end
  if entity.health then
    entry.health = common.rounded(entity.health)
  end
  local contents = entities.contents(entity)
  if next(contents) then
    entry.items = contents
  end
  local fluids_ok, fluids = pcall(entity.get_fluid_contents)
  if fluids_ok and next(fluids) then
    entry.fluids = {}
    for fluid, amount in pairs(fluids) do
      entry.fluids[fluid] = common.rounded(amount)
    end
  end
  entry.lanes = belts.lanes(entity)
  local recipe_ok, recipe = pcall(entity.get_recipe)
  if recipe_ok and recipe then
    entry.recipe = recipe.name
  end
  entry.status = entities.status(entity)
  return entry
end

return entities
