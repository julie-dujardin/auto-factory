local common = require("scripts.common")
local ids = require("scripts.ids")

local rounded = common.rounded
local handlers = {}

-- Expected count per craft or mining cycle, so chance-based products compare fairly.
local function expected_amount(product)
  local amount = product.amount or (product.amount_min + product.amount_max) / 2
  local probability = product.probability or product.independent_probability or 1
  return (amount + (product.extra_count_fraction or 0)) * probability
end

local function amounts(list)
  local result = {}
  for _, entry in pairs(list or {}) do
    result[entry.name] = rounded((result[entry.name] or 0) + expected_amount(entry))
  end
  return result
end

local function power_needs(prototype)
  local source = "none"
  if prototype.burner_prototype then
    source = "burner"
  elseif prototype.electric_energy_source_prototype then
    source = "electric"
  elseif prototype.fluid_energy_source_prototype then
    source = "fluid"
  elseif prototype.heat_energy_source_prototype then
    source = "heat"
  end
  return source, prototype.energy_usage and rounded(prototype.energy_usage * 60 / 1000)
end

-- Items the force can already make, so the agent knows which machines it can build.
local function craftable_items(force)
  local items = {}
  for _, recipe in pairs(force.recipes) do
    if recipe.enabled then
      for _, product in pairs(recipe.prototype.products) do
        items[product.name] = true
      end
    end
  end
  return items
end

-- The character is listed as "hand"; it needs no power and is never built.
local function machine_entry(prototype, craftable, speed, seconds_per_cycle, amount)
  local seconds = seconds_per_cycle / speed
  local entry = {
    speed = rounded(speed),
    seconds = rounded(seconds),
    per_minute = rounded(amount * 60 / seconds),
  }
  if prototype.type ~= "character" then
    entry.energy, entry.kw = power_needs(prototype)
    entry.buildable = craftable[prototype.items_to_place_this[1].name] == true
  end
  return entry
end

-- Unplaceable machines such as crash-site wrecks would only mislead.
local function usable_machine(prototype)
  if prototype.hidden then
    return false
  end
  return prototype.type == "character" or next(prototype.items_to_place_this or {}) ~= nil
end

local function runs_recipe(prototype, recipe)
  for _, category in pairs(recipe.categories) do
    if prototype.crafting_categories[category] then
      return true
    end
  end
  return false
end

local function machine_key(prototype)
  return prototype.type == "character" and "hand" or prototype.name
end

local function unlocking_technologies(recipe_name)
  local names = {}
  for name, technology in pairs(prototypes.technology) do
    for _, effect in pairs(technology.effects or {}) do
      if effect.type == "unlock-recipe" and effect.recipe == recipe_name then
        table.insert(names, name)
      end
    end
  end
  return names
end

local function machines_for(character)
  local crafters = {}
  local miners = {}
  for _, prototype in pairs(prototypes.entity) do
    local is_player = prototype.type == "character"
    if usable_machine(prototype) and (not is_player or prototype.name == character.name) then
      if prototype.crafting_categories then
        table.insert(crafters, prototype)
      end
      if prototype.resource_categories then
        table.insert(miners, prototype)
      end
    end
  end
  return crafters, miners
end

local function recipes_making(name, force, crafters, craftable)
  local recipes = {}
  for recipe_name, recipe in pairs(prototypes.recipe) do
    local made = amounts(recipe.products)[name]
    -- Emptying a barrel only returns fluid that was already made elsewhere.
    if made and not recipe.hidden and recipe.subgroup.name ~= "empty-barrel" then
      local machines = {}
      for _, prototype in pairs(crafters) do
        if runs_recipe(prototype, recipe) then
          machines[machine_key(prototype)] = machine_entry(
            prototype, craftable, prototype.get_crafting_speed(), recipe.energy, made
          )
        end
      end
      local entry = {
        unlocked = force.recipes[recipe_name].enabled,
        categories = recipe.categories,
        seconds = rounded(recipe.energy),
        ingredients = amounts(recipe.ingredients),
        products = amounts(recipe.products),
        machines = machines,
      }
      local technologies = not entry.unlocked and unlocking_technologies(recipe_name)
      if technologies and #technologies > 0 then
        entry.unlocked_by = technologies
      end
      recipes[recipe_name] = entry
    end
  end
  return recipes
end

local function resources_yielding(name, miners, craftable)
  local mining = {}
  for resource_name, resource in pairs(prototypes.entity) do
    local mineable = resource.type == "resource" and resource.mineable_properties
    local made = mineable and mineable.minable and amounts(mineable.products)[name]
    if made then
      local drills = {}
      for _, prototype in pairs(miners) do
        if prototype.resource_categories[resource.resource_category] then
          drills[machine_key(prototype)] = machine_entry(
            prototype, craftable, prototype.mining_speed, mineable.mining_time, made
          )
        end
      end
      mining[resource_name] = {
        seconds = rounded(mineable.mining_time),
        required_fluid = mineable.required_fluid,
        -- Oil-like fields scale output by their yield, which the base rate ignores.
        rate_scales_with_yield = resource.infinite_resource or nil,
        machines = drills,
      }
    end
  end
  return mining
end

function handlers.recipe(params)
  local player = common.get_player(params)
  local name = ids.check(common.required_string(params, "item"), "item", "fluid")
  local force = player.force
  local craftable = craftable_items(force)
  local crafters, miners = machines_for(player.character.prototype)
  local recipes = recipes_making(name, force, crafters, craftable)
  local mining = resources_yielding(name, miners, craftable)
  if next(recipes) == nil and next(mining) == nil then
    common.fail("nothing makes " .. name)
  end
  return {item = name, recipes = recipes, mining = mining}
end

return {handlers = handlers}
