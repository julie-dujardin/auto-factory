local actions = require("scripts.actions")
local belts = require("scripts.belts")
local common = require("scripts.common")
local entities = require("scripts.entities")
local ids = require("scripts.ids")
local research = require("scripts.research")

local handlers = {}

local OBSERVABLE_TYPES = {
  "accumulator",
  "ammo-turret",
  "assembling-machine",
  "beacon",
  "boiler",
  "burner-generator",
  "car",
  "cargo-wagon",
  "container",
  "electric-pole",
  "furnace",
  "generator",
  "inserter",
  "item-entity",
  "lab",
  "lamp",
  "loader",
  "locomotive",
  "logistic-container",
  "mining-drill",
  "offshore-pump",
  "pipe",
  "pipe-to-ground",
  "pump",
  "radar",
  "reactor",
  "roboport",
  "rocket-silo",
  "simple-entity",
  "solar-panel",
  "splitter",
  "storage-tank",
  "train-stop",
  "transport-belt",
  "tree",
  "turret",
  "underground-belt",
}

-- Entries after folding transport belts into runs, nearest first.
local NEARBY_LISTED = 100

function handlers.observe(params)
  local player = common.get_player(params)
  local radius = math.max(2, math.min(64, tonumber(params.radius) or 12))
  local resources = {}
  local resource_entities = player.surface.find_entities_filtered {
    position = player.position,
    radius = radius,
    type = "resource",
    limit = 1000,
  }
  for _, entity in pairs(resource_entities) do
    local summary = resources[entity.name]
    local distance = common.distance_squared(player.position, entity.position)
    if not summary then
      summary = {count = 0, amount = 0, nearest = nil, nearest_distance = nil}
      resources[entity.name] = summary
    end
    summary.count = summary.count + 1
    summary.amount = summary.amount + entity.amount
    if summary.nearest_distance == nil or distance < summary.nearest_distance then
      summary.nearest = common.offset_from(player.position, entity.position)
      summary.nearest_distance = distance
    end
  end
  for _, summary in pairs(resources) do
    summary.nearest_distance = nil
  end

  local nearby = player.surface.find_entities_filtered {
    position = player.position,
    radius = radius,
    type = OBSERVABLE_TYPES,
  }
  local origin = player.position
  local transport_belts = {}
  local candidates = {}
  for _, entity in pairs(nearby) do
    if entity.type == "transport-belt" then
      table.insert(transport_belts, entity)
    else
      table.insert(candidates, {
        entity = entity,
        distance = common.distance_squared(origin, entity.position),
      })
    end
  end
  for _, run in pairs(belts.runs(transport_belts, origin)) do
    table.insert(candidates, run)
  end
  table.sort(candidates, function(a, b) return a.distance < b.distance end)
  local nearby_entries = {}
  for index = 1, math.min(NEARBY_LISTED, #candidates) do
    local candidate = candidates[index]
    table.insert(nearby_entries, candidate.entry or entities.entry(candidate.entity, origin))
  end

  return {
    tick = game.tick,
    speed = game.speed,
    player = {
      index = player.index,
      name = player.name,
      world_position = common.plain_position(player.position),
      health = player.character.health,
      inventory = entities.inventory_contents(player.get_main_inventory()),
      crafting_queue_size = player.crafting_queue_size,
      crafting_progress = common.rounded(player.crafting_queue_progress),
      action = actions.current_summary(player),
    },
    research = research.state(player.force),
    radius = radius,
    resources = resources,
    entities = nearby_entries,
  }
end

local FIND_SORTS = {distance = true, amount = true, name = true}

-- Substring names are resolved to prototypes so the engine does the spatial filtering.
local function matching_entity_names(fragment)
  local names = {}
  for name in pairs(prototypes.entity) do
    if string.find(name, fragment, 1, true) then
      table.insert(names, name)
    end
  end
  if #names == 0 then
    -- Fails, since no entity name contains fragment, listing similar names.
    ids.check(fragment, "entity")
  end
  return names
end

function handlers.find(params)
  local player = common.get_player(params)
  local radius = math.max(1, math.min(256, common.required_number(params, "radius")))
  local limit = math.max(1, math.min(50, math.floor(common.required_number(params, "limit"))))
  local sort = params.sort or "distance"
  if not FIND_SORTS[sort] then
    common.fail("sort must be distance, amount, or name")
  end
  local name = params.name or ""
  local entity_type = params.type or ""
  -- The engine matches nothing for an unknown type or status, which reads as "none
  -- nearby".
  local status = params.status or ""
  if status ~= "" then
    ids.check(status, "status")
  end
  if name == "" and entity_type == "" then
    common.fail("give a name or type filter")
  end

  local filter = {position = player.position, radius = radius}
  if name ~= "" then
    filter.name = matching_entity_names(name)
  end
  if entity_type ~= "" then
    filter.type = ids.check(entity_type, "entity_type")
  end
  local found_ok, found = pcall(player.surface.find_entities_filtered, filter)
  if not found_ok then
    common.fail(tostring(found))
  end

  local origin = player.position
  local matches = {}
  local totals = {}
  for _, entity in pairs(found) do
    if entity.valid and (status == "" or entities.status(entity) == status) then
      local match = {
        entity = entity,
        distance = common.distance_squared(origin, entity.position),
        amount = sort == "amount" and entities.amount(entity) or nil,
      }
      table.insert(matches, match)
      local total = totals[entity.name]
      if not total then
        total = {count = 0}
        totals[entity.name] = total
      end
      total.count = total.count + 1
      if entity.type == "resource" then
        total.amount = (total.amount or 0) + entity.amount
      end
    end
  end

  if sort == "distance" then
    table.sort(matches, function(a, b) return a.distance < b.distance end)
  elseif sort == "amount" then
    table.sort(matches, function(a, b)
      if a.amount ~= b.amount then return a.amount > b.amount end
      return a.distance < b.distance
    end)
  else
    table.sort(matches, function(a, b)
      if a.entity.name ~= b.entity.name then return a.entity.name < b.entity.name end
      return a.distance < b.distance
    end)
  end

  local results = {}
  for index = 1, math.min(limit, #matches) do
    local match = matches[index]
    local entry = entities.entry(match.entity, origin)
    entry.distance = common.rounded(math.sqrt(match.distance))
    table.insert(results, entry)
  end
  return {
    radius = radius,
    matched = #matches,
    totals = totals,
    entities = results,
  }
end

return {handlers = handlers}
