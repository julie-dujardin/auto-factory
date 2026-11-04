local common = require("scripts.common")
local ids = require("scripts.ids")

local research = {handlers = {}}

local STATUSES = {available = true, queued = true, locked = true, researched = true, any = true}
local COMPLETIONS = {labs = true, trigger = true, any = true}

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

local function total_packs(technology)
  local per_unit = 0
  for _, ingredient in pairs(technology.research_unit_ingredients) do
    per_unit = per_unit + ingredient.amount
  end
  return per_unit * technology.research_unit_count
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

local function queue_positions(force)
  local positions = {}
  for index, technology in pairs(force.research_queue or {}) do
    positions[technology.name] = index
  end
  return positions
end

local function status(technology, queued)
  if technology.researched then
    return "researched"
  end
  if not technology.enabled then
    return "disabled"
  end
  local position = queued[technology.name]
  if position then
    return position == 1 and "researching" or "queued"
  end
  return ready(technology) and "available" or "locked"
end

local function unlocked_recipes(prototype)
  local recipes = {}
  for _, effect in pairs(prototype.effects or {}) do
    if effect.type == "unlock-recipe" and ids.listed_recipe(prototypes.recipe[effect.recipe]) then
      table.insert(recipes, effect.recipe)
    end
  end
  return recipes
end

local function unlocks_product(prototype, product)
  if product == "" then
    return true
  end
  for _, recipe in pairs(unlocked_recipes(prototype)) do
    if recipe == product then
      return true
    end
    -- Emptying a barrel only returns fluid that was already made elsewhere.
    local recipe_prototype = prototypes.recipe[recipe]
    if recipe_prototype.subgroup.name ~= "empty-barrel" then
      for _, each in pairs(recipe_prototype.products) do
        if each.name == product then
          return true
        end
      end
    end
  end
  return false
end

-- With packs given, only lab technologies needing no other pack match.
local function needs_only(technology, packs)
  if not next(packs) then
    return true
  end
  if technology.prototype.research_trigger then
    return false
  end
  for _, ingredient in pairs(technology.research_unit_ingredients) do
    if not packs[ingredient.name] then
      return false
    end
  end
  return true
end

local function level(technology)
  local prototype = technology.prototype
  return prototype.max_level > prototype.level and technology.level or nil
end

-- TODO: a tool listing the research bonuses in effect (force modifiers such as
-- mining_drill_productivity_bonus, and per-recipe productivity).
function research.state(force)
  local current = force.current_research
  local previous = force.previous_research
  local queue = {}
  for _, technology in pairs(force.research_queue or {}) do
    table.insert(queue, technology.name)
  end
  local queued = queue_positions(force)
  local available = 0
  local triggers = 0
  local researched = 0
  for _, technology in pairs(force.technologies) do
    local state = status(technology, queued)
    if state == "researched" then
      researched = researched + 1
    elseif state == "available" and not technology.prototype.hidden then
      if technology.prototype.research_trigger then
        triggers = triggers + 1
      else
        available = available + 1
      end
    end
  end
  return {
    current = current and current.name,
    progress = current and common.rounded(force.research_progress),
    queue = queue,
    last_researched = previous and previous.name,
    researched = researched,
    available = available,
    triggers = triggers,
  }
end

function research.handlers.technologies(params)
  local player = common.get_player(params)
  local force = player.force
  local query = params.query or ""
  local wanted = params.status or "available"
  if not STATUSES[wanted] then
    common.fail("status must be available, queued, locked, researched, or any")
  end
  local completes_by = params.completes_by or "any"
  if not COMPLETIONS[completes_by] then
    common.fail("completes_by must be labs, trigger, or any")
  end
  local packs = {}
  for _, pack in pairs(params.packs or {}) do
    packs[ids.check(pack, "item")] = true
  end
  local unlocks = params.unlocks or ""
  if unlocks ~= "" then
    ids.check(unlocks, "item", "fluid", "recipe")
  end
  local limit = math.max(1, math.min(50, math.floor(common.required_number(params, "limit"))))

  local queued = queue_positions(force)
  local states = {}
  local names = {}
  for name, technology in pairs(force.technologies) do
    local prototype = technology.prototype
    local state = status(technology, queued)
    local completion = prototype.research_trigger and "trigger" or "labs"
    if not prototype.hidden
      and state ~= "disabled"
      and (wanted == "any" or wanted == state or (wanted == "queued" and state == "researching"))
      and (completes_by == "any" or completes_by == completion)
      and needs_only(technology, packs)
      and unlocks_product(prototype, unlocks)
    then
      states[name] = state
      table.insert(names, name)
    end
  end
  if query ~= "" then
    names = ids.ranked(query, names)
  else
    local totals = {}
    for _, name in pairs(names) do
      totals[name] = total_packs(force.technologies[name])
    end
    table.sort(names, function(a, b)
      if totals[a] ~= totals[b] then
        return totals[a] < totals[b]
      end
      return a < b
    end)
  end

  local results = {}
  for index = 1, math.min(limit, #names) do
    local technology = force.technologies[names[index]]
    local trigger = technology.prototype.research_trigger
    local recipes = unlocked_recipes(technology.prototype)
    local state = states[technology.name]
    results[index] = {
      technology = technology.name,
      status = state,
      level = level(technology),
      cost = not trigger and cost(technology) or nil,
      trigger = trigger and trigger_entry(trigger),
      progress = progress(force, technology),
      unlocks = next(recipes) and recipes or nil,
      missing = state == "locked" and #missing_prerequisites(technology) or nil,
    }
  end
  return {matched = #names, technologies = results}
end

function research.handlers.technology(params)
  local player = common.get_player(params)
  local name = ids.check(common.required_string(params, "technology"), "technology")
  local force = player.force
  local technology = force.technologies[name]
  local prototype = technology.prototype
  local effects = {}
  for _, effect in pairs(prototype.effects or {}) do
    if effect.type ~= "unlock-recipe" and not effect.hidden then
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
    status = status(technology, queue_positions(force)),
    level = level(technology),
    cost = not trigger and cost(technology) or nil,
    trigger = trigger and trigger_entry(trigger),
    progress = progress(force, technology),
    unlocks_recipes = unlocked_recipes(prototype),
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
