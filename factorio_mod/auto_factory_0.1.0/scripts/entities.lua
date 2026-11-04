local belts = require("scripts.belts")
local common = require("scripts.common")
local ids = require("scripts.ids")
local info = require("scripts.info")

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

-- Entry field per inventory name; chests, trunks, ammo and the rest go to items.
local INVENTORY_FIELDS = {
  agricultural_tower_input = "input_slots",
  agricultural_tower_modules = "modules",
  agricultural_tower_output = "output_slots",
  assembling_machine_dump = "trash",
  beacon_modules = "modules",
  burnt_result = "burnt_result",
  crafter_input = "input_slots",
  crafter_modules = "modules",
  crafter_output = "output_slots",
  crafter_trash = "trash",
  fuel = "fuel",
  lab_input = "input_slots",
  lab_modules = "modules",
  lab_trash = "trash",
  mining_drill_modules = "modules",
}

-- Item counts per entry field, so a machine's ingredients, products and fuel stay apart.
local function held_by_field(entity)
  if entity.type == "item-entity" then
    return {items = {[entity.stack.name] = entity.stack.count}}
  end
  local fields = {}
  for index = 1, entity.get_max_inventory_index() do
    local inventory = entity.get_inventory(index)
    if inventory and inventory.valid and not inventory.is_empty() then
      local field = INVENTORY_FIELDS[inventory.name] or "items"
      local counts = fields[field] or {}
      for name, count in pairs(entities.inventory_contents(inventory)) do
        counts[name] = (counts[name] or 0) + count
      end
      fields[field] = counts
    end
  end
  return fields
end

local FLUID_FIELDS = {input = "input_fluids", output = "output_fluids"}

-- Fluid amounts per entry field, from what each fluidbox does in the recipe.
local function fluids_by_field(entity)
  local fields = {}
  for index = 1, entity.fluids_count do
    local fluid = entity.get_fluid(index)
    if fluid then
      -- A crafting machine's recipe can merge prototypes, returned as an array.
      local prototype = entity.get_fluid_box_prototype(index)
      if prototype and not prototype.object_name then
        prototype = prototype[1]
      end
      local field = prototype and FLUID_FIELDS[prototype.production_type] or "fluids"
      local amounts = fields[field] or {}
      amounts[fluid.name] = common.rounded((amounts[fluid.name] or 0) + fluid.amount)
      fields[field] = amounts
    end
  end
  return fields
end

function entities.contents(entity)
  local result = {}
  for _, counts in pairs(held_by_field(entity)) do
    for name, count in pairs(counts) do
      result[name] = (result[name] or 0) + count
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

-- An entity's id is its unit number. The engine looks unit numbers up only for a few
-- prototypes, so every entity given out with an id is remembered here.
function entities.id(entity)
  local id = entity.unit_number
  if id then
    storage.entity_ids = storage.entity_ids or {}
    storage.entity_ids[id] = entity
  end
  return id
end

function entities.by_id(id)
  local entity = storage.entity_ids and storage.entity_ids[id]
  if not entity then
    common.fail("no entity has id " .. id .. "; ids come from api_scan, api_find, api_place, and api_connect")
  end
  if not entity.valid then
    storage.entity_ids[id] = nil
    common.fail("entity " .. id .. " is gone")
  end
  return entity
end

local FIND_RADIUS = 0.8
local NEARBY_RADIUS = 32
local NEARBY_LISTED = 5

-- The entity params name: by id, or when id is 0 by entity name at dx/dy.
function entities.target(player, params)
  local id = math.floor(tonumber(params.id) or 0)
  if id ~= 0 then
    return entities.by_id(id)
  end
  local name = common.required_string(params, "entity")
  local position = common.position_from(player, params)
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
  local requested = common.offset_text(common.origin(player), position)
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
    table.insert(offsets, common.offset_text(common.origin(player), nearby[index].position))
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

-- Power switches merge sub networks into a parent sharing power, so the parent is the
-- network, named by its lowest sub network id. Each one is added to networks once.
local function network_id(pole, networks)
  local sub_network = pole.electric_network
  if not sub_network then
    return nil
  end
  local parent = sub_network.parent_network
  local id = sub_network.id
  for _, other in pairs(parent.sub_networks) do
    id = math.min(id, other.id)
  end
  for _, known in pairs(networks) do
    if known.id == id then
      return id
    end
  end
  local flow = parent.flow_last_tick
  table.insert(networks, {
    id = id,
    available_kw = common.rounded(flow.maximum_production * 60 / 1000),
    demand_kw = common.rounded(flow.maximum_consumption * 60 / 1000),
  })
  return id
end

local function area_from(origin, area)
  return {
    left_top = common.offset_from(origin, area.left_top),
    right_bottom = common.offset_from(origin, area.right_bottom),
  }
end

local function supply_area(pole, origin)
  local reach = pole.prototype.get_supply_area_distance(pole.quality)
  local position = pole.position
  return area_from(origin, {
    left_top = {x = position.x - reach, y = position.y - reach},
    right_bottom = {x = position.x + reach, y = position.y + reach},
  })
end

-- Amount left per resource the drill can mine in its area; infinite resources such as
-- crude oil give their yield instead, as api_resources does.
local function mined_resources(drill)
  local categories = drill.prototype.resource_categories
  local amounts = {}
  local normal_amounts = {}
  for _, resource in pairs(drill.surface.find_entities_filtered {
    area = drill.mining_area,
    type = "resource",
  }) do
    local prototype = resource.prototype
    if categories[prototype.resource_category] then
      amounts[resource.name] = (amounts[resource.name] or 0) + resource.amount
      if prototype.infinite_resource then
        normal_amounts[resource.name] = prototype.normal_resource_amount
      end
    end
  end
  for name, normal in pairs(normal_amounts) do
    amounts[name] = {yield_percent = math.floor(amounts[name] / normal * 100 + 0.5)}
  end
  return amounts
end

local function holds_items(entity)
  if entity.prototype.belt_speed or entity.type == "item-entity" then
    return true
  end
  for index = 1, entity.get_max_inventory_index() do
    if entity.get_inventory(index) then
      return true
    end
  end
  return false
end

-- What an inserter or drill reaches on side, pickup or drop: a belt or an entity holding
-- items. The engine sets pickup_target and drop_target only in a later tick than the
-- build.
local function holder_at(reacher, side)
  local target = reacher[side .. "_target"]
  if target then
    return target
  end
  for _, other in pairs(reacher.surface.find_entities_filtered {position = reacher[side .. "_position"]}) do
    if other ~= reacher and other.type ~= "character" and holds_items(other) then
      return other
    end
  end
  return nil
end

-- The holder reacher reaches on side with what it carries there: a belt's lanes on that
-- tile, a crafting machine's recipe, or else the items it holds.
local function endpoint(reacher, side)
  local holder = holder_at(reacher, side)
  if not holder then
    return nil
  end
  local result = {id = entities.id(holder), name = holder.name}
  local crafts, recipe = pcall(holder.get_recipe)
  if holder.prototype.belt_speed then
    result.lanes = belts.lanes(holder)
  elseif crafts then
    result.recipe = recipe and recipe.name
  else
    local items = entities.contents(holder)
    result.items = next(items) and items or nil
  end
  return result
end

local function inserter_filters(inserter)
  local items = {}
  for slot = 1, inserter.filter_slot_count do
    local filter = inserter.get_filter(slot)
    if filter and filter.name then
      table.insert(items, filter.name)
    end
  end
  return items
end

function entities.label(entity)
  local id = entities.id(entity)
  return id and entity.name .. " #" .. id or entity.name
end

local function labels(list)
  local result = {}
  for _, entity in pairs(list) do
    table.insert(result, entities.label(entity))
  end
  return #result > 0 and result or nil
end

-- Long-handed inserters reach 2 tiles past the tile next to them.
local FEEDER_REACH = 3

-- Inserters and drills around entity that drop into it, and inserters that take from it.
local function feeders(entity)
  local position = entity.position
  local reach_x = entity.tile_width / 2 + FEEDER_REACH
  local reach_y = entity.tile_height / 2 + FEEDER_REACH
  local fed_by, emptied_by = {}, {}
  for _, other in pairs(entity.surface.find_entities_filtered {
    area = {
      left_top = {x = position.x - reach_x, y = position.y - reach_y},
      right_bottom = {x = position.x + reach_x, y = position.y + reach_y},
    },
    type = {"inserter", "mining-drill"},
  }) do
    if holder_at(other, "drop") == entity then
      table.insert(fed_by, other)
    end
    if other.type == "inserter" and holder_at(other, "pickup") == entity then
      table.insert(emptied_by, other)
    end
  end
  return fed_by, emptied_by
end

local CRAFTER_TYPES = {["assembling-machine"] = true, furnace = true, ["rocket-silo"] = true}

-- True without a recipe too, as one with item products may come.
local function makes_items(crafter)
  local recipe = crafter.get_recipe()
  if not recipe then
    return true
  end
  for _, product in pairs(recipe.products) do
    if product.type == "item" then
      return true
    end
  end
  return false
end

local function feeder_links(entity, links, warnings)
  local fed_by, emptied_by = feeders(entity)
  links.fed_by = labels(fed_by)
  links.emptied_by = labels(emptied_by)
  if CRAFTER_TYPES[entity.type] and #emptied_by == 0 and makes_items(entity) then
    table.insert(warnings, "products stay in output_slots until an inserter takes them")
  end
end

-- Collects the electric networks of listed poles into networks.
function entities.entry(entity, origin, networks)
  local entry = {
    id = entities.id(entity),
    name = entity.name,
    type = entity.type,
    position = common.offset_from(origin, entity.position),
  }
  if entity.supports_direction then
    entry.direction, entry.pipes_face = info.shown_facing(entity.prototype, entity.direction)
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
    entry.network = network_id(entity, networks)
  end
  if entity.type == "mining-drill" then
    entry.mining_area = area_from(origin, entity.mining_area)
    entry.mines = mined_resources(entity)
  end
  if entity.health then
    entry.health = common.rounded(entity.health)
  end
  for field, counts in pairs(held_by_field(entity)) do
    entry[field] = counts
  end
  if entity.type == "inserter" then
    if entity.held_stack.valid_for_read then
      entry.held = {[entity.held_stack.name] = entity.held_stack.count}
    end
    if entity.filter_slot_count > 0 and entity.use_filters then
      entry.filter_mode = entity.inserter_filter_mode
      entry.filters = inserter_filters(entity)
    end
    local override = entity.inserter_stack_size_override
    entry.stack_size_override = override > 0 and override or nil
    entry.takes_from = endpoint(entity, "pickup") or "nothing"
  end
  if entity.type == "inserter" or entity.type == "mining-drill" then
    entry.gives_to = endpoint(entity, "drop") or "ground"
  end
  if entity.type == "splitter" then
    entry.input_priority = entity.splitter_input_priority
    entry.output_priority = entity.splitter_output_priority
    entry.filter = entity.splitter_filter and entity.splitter_filter.name
  end
  if CRAFTER_TYPES[entity.type] then
    local warnings = {}
    feeder_links(entity, entry, warnings)
    entry.warnings = #warnings > 0 and warnings or nil
  end
  local fluids_ok, fluid_fields = pcall(fluids_by_field, entity)
  if fluids_ok then
    for field, amounts in pairs(fluid_fields) do
      entry[field] = amounts
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

local function uses_electricity(entity)
  return entity.type ~= "electric-pole" and entity.prototype.electric_energy_source_prototype ~= nil
end

local function produces_power(entity)
  return entity.prototype.get_max_energy_production() > 0
end

local function pole_links(pole, links, warnings)
  local reach = pole.prototype.get_supply_area_distance(pole.quality)
  local position = pole.position
  local covered = pole.surface.find_entities_filtered {
    area = {
      left_top = {x = position.x - reach, y = position.y - reach},
      right_bottom = {x = position.x + reach, y = position.y + reach},
    },
  }
  local powers, has_generator = 0, false
  for _, other in pairs(covered) do
    if uses_electricity(other) or (other.type ~= "electric-pole" and produces_power(other)) then
      powers = powers + 1
      has_generator = has_generator or produces_power(other)
    end
  end
  links.powers = powers
  local wired = {}
  local connector = pole.get_wire_connector(defines.wire_connector_id.pole_copper, false)
  for _, connection in pairs(connector and connector.connections or {}) do
    table.insert(wired, connection.target.owner)
  end
  links.wired_to = labels(wired)
  if #wired == 0 and not has_generator then
    table.insert(warnings, "wired to no pole and no generator in its supply area")
  end
end

-- Entities joined to entity's fluidboxes, each once.
local function fluid_neighbours(entity)
  local result, seen = {}, {}
  for index = 1, entity.fluids_count do
    for _, connection in pairs(entity.get_fluid_box_pipe_connections(index)) do
      local target = connection.target
      if target and target ~= entity and not seen[target.unit_number or target] then
        seen[target.unit_number or target] = true
        table.insert(result, target)
      end
    end
  end
  return result
end

-- What a just-built entity connects to, with warnings for ends that lead nowhere.
function entities.links(entity, origin)
  local links = {id = entities.id(entity), position = common.offset_from(origin, entity.position)}
  local warnings = {}
  if entity.type == "inserter" or entity.type == "mining-drill" then
    if entity.type == "inserter" then
      links.takes_from = endpoint(entity, "pickup")
      if not links.takes_from then
        table.insert(warnings, "takes from nothing")
      end
    end
    links.gives_to = endpoint(entity, "drop")
    if not links.gives_to then
      table.insert(warnings, "drops onto the ground")
    end
  elseif entity.type == "electric-pole" then
    pole_links(entity, links, warnings)
  else
    feeder_links(entity, links, warnings)
  end
  if entity.prototype.belt_speed then
    local neighbours = entity.belt_neighbours
    links.belt_from = labels(neighbours.inputs)
    links.belt_to = labels(neighbours.outputs)
  end
  links.fluid_to = labels(fluid_neighbours(entity))
  if uses_electricity(entity) and not entity.is_connected_to_electric_network() then
    table.insert(warnings, "not powered")
  end
  links.warnings = #warnings > 0 and warnings or nil
  return links
end

return entities
