local common = require("scripts.common")
local ids = require("scripts.ids")

local research = {handlers = {}}

-- Force modifiers that change how the factory or the character performs; all default to 0.
-- The scan's player distances already include the reach bonuses.
local BONUSES = {
  "mining_drill_productivity_bonus",
  "inserter_stack_size_bonus",
  "bulk_inserter_capacity_bonus",
  "belt_stack_size_bonus",
  "laboratory_speed_modifier",
  "laboratory_productivity_bonus",
  "worker_robots_speed_modifier",
  "worker_robots_storage_bonus",
  "worker_robots_battery_modifier",
  "character_inventory_slots_bonus",
  "character_running_speed_modifier",
  "manual_crafting_speed_modifier",
  "manual_mining_speed_modifier",
}

local function ready(technology)
  for _, prerequisite in pairs(technology.prerequisites) do
    if not prerequisite.researched then
      return false
    end
  end
  return true
end

-- research_unit_energy is in ticks.
local function cost(technology)
  local packs = {}
  for _, ingredient in pairs(technology.research_unit_ingredients) do
    packs[ingredient.name] = ingredient.amount
  end
  return {
    units = technology.research_unit_count,
    packs = packs,
    seconds = common.rounded(technology.research_unit_energy / 60),
  }
end

local function trigger_entry(trigger)
  return {
    type = trigger.type,
    item = trigger.item and trigger.item.name,
    entities = trigger.entities,
    entity = trigger.entity and (trigger.entity.name or trigger.entity),
    fluid = trigger.fluid,
    count = trigger.count or trigger.amount,
  }
end

local function progress(force, technology)
  local current = force.current_research
  local fraction = technology.saved_progress
  if current and current.name == technology.name then
    fraction = force.research_progress
  end
  return fraction > 0 and common.rounded(fraction) or nil
end

local function bonuses(force)
  local result = {}
  for _, field in pairs(BONUSES) do
    if force[field] ~= 0 then
      result[field] = common.rounded(force[field])
    end
  end
  local productivity = {}
  for name, recipe in pairs(force.recipes) do
    if recipe.productivity_bonus ~= 0 then
      productivity[name] = common.rounded(recipe.productivity_bonus)
    end
  end
  result.recipe_productivity = next(productivity) and productivity or nil
  return result
end

-- The unresearched technologies this one depends on, each after its own prerequisites.
local function missing_prerequisites(technology)
  local order = {}
  local seen = {}
  local function visit(each)
    for name, prerequisite in pairs(each.prerequisites) do
      if not prerequisite.researched and not seen[name] then
        seen[name] = true
        visit(prerequisite)
        table.insert(order, name)
      end
    end
  end
  visit(technology)
  return order
end

local function status(force, technology)
  if technology.researched then
    return "researched"
  end
  if not technology.enabled then
    return "disabled"
  end
  for index, queued in pairs(force.research_queue or {}) do
    if queued.name == technology.name then
      return index == 1 and "researching" or "queued"
    end
  end
  return ready(technology) and "available" or "locked"
end

function research.state(force)
  local current = force.current_research
  local previous = force.previous_research
  local queue = {}
  for _, technology in pairs(force.research_queue or {}) do
    table.insert(queue, technology.name)
  end
  local available = {}
  local triggers = {}
  local researched = 0
  for name, technology in pairs(force.technologies) do
    if technology.researched then
      researched = researched + 1
    end
    if technology.enabled and not technology.researched and ready(technology) then
      local trigger = technology.prototype.research_trigger
      if trigger then
        triggers[name] = trigger_entry(trigger)
      else
        local entry = cost(technology)
        entry.progress = progress(force, technology)
        available[name] = entry
      end
    end
  end
  return {
    current = current and current.name,
    progress = current and common.rounded(force.research_progress),
    queue = queue,
    last_researched = previous and previous.name,
    available = available,
    triggers = triggers,
    researched = researched,
    bonuses = bonuses(force),
  }
end

function research.handlers.technology(params)
  local player = common.get_player(params)
  local name = ids.check(common.required_string(params, "technology"), "technology")
  local force = player.force
  local technology = force.technologies[name]
  local prototype = technology.prototype
  local recipes = {}
  local effects = {}
  for _, effect in pairs(prototype.effects or {}) do
    if effect.type == "unlock-recipe" then
      table.insert(recipes, effect.recipe)
    elseif not effect.hidden then
      effect.hidden = nil
      table.insert(effects, effect)
    end
  end
  local prerequisites = {}
  for prerequisite in pairs(technology.prerequisites) do
    table.insert(prerequisites, prerequisite)
  end
  local successors = {}
  for successor in pairs(technology.successors) do
    table.insert(successors, successor)
  end
  table.sort(prerequisites)
  table.sort(successors)
  local trigger = prototype.research_trigger
  return {
    technology = name,
    status = status(force, technology),
    level = prototype.max_level > prototype.level and technology.level or nil,
    cost = not trigger and cost(technology) or nil,
    trigger = trigger and trigger_entry(trigger),
    progress = progress(force, technology),
    unlocks_recipes = recipes,
    effects = effects,
    prerequisites = prerequisites,
    missing_prerequisites = missing_prerequisites(technology),
    successors = successors,
  }
end

function research.handlers.research(params)
  local player = common.get_player(params)
  local name = ids.check(common.required_string(params, "technology"), "technology")
  local force = player.force
  local technology = force.technologies[name]
  if technology.researched then
    common.fail(name .. " is already researched")
  end
  if technology.prototype.research_trigger then
    common.fail(name .. " is unlocked by its trigger, not by labs")
  end
  if not force.add_research(technology) then
    local missing = missing_prerequisites(technology)
    if #missing > 0 then
      common.fail("could not queue " .. name .. "; it needs these first, in order: "
        .. table.concat(missing, ", "))
    end
    common.fail("could not queue " .. name)
  end
  return research.state(force)
end

return research
