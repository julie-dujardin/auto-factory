local common = require("scripts.common")

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

function entities.find(player, name, position)
  local candidates = player.surface.find_entities_filtered {
    position = position,
    radius = 0.8,
    name = name,
    limit = 10,
  }
  local closest = nil
  local closest_distance = nil
  for _, entity in pairs(candidates) do
    local distance = common.distance_squared(position, entity.position)
    if closest_distance == nil or distance < closest_distance then
      closest = entity
      closest_distance = distance
    end
  end
  if not closest then
    common.fail("no " .. name .. " found near the requested position")
  end
  return closest
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
  if entity.health then
    entry.health = common.rounded(entity.health)
  end
  local contents = entities.contents(entity)
  if next(contents) then
    entry.items = contents
  end
  local recipe_ok, recipe = pcall(entity.get_recipe)
  if recipe_ok and recipe then
    entry.recipe = recipe.name
  end
  entry.status = entities.status(entity)
  return entry
end

return entities
