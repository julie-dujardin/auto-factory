local common = require("scripts.common")

local research = {handlers = {}}

function research.state(force)
  local current = force.current_research
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
    if technology.enabled and not technology.researched then
      local ready = true
      for _, prerequisite in pairs(technology.prerequisites) do
        if not prerequisite.researched then
          ready = false
          break
        end
      end
      if ready then
        local trigger = technology.prototype.research_trigger
        if trigger then
          triggers[name] = {
            type = trigger.type,
            item = trigger.item and trigger.item.name,
            entity = trigger.entity and (trigger.entity.name or trigger.entity),
            fluid = trigger.fluid,
            count = trigger.count or trigger.amount,
          }
        else
          table.insert(available, name)
        end
      end
    end
  end
  table.sort(available)
  return {
    current = current and current.name,
    progress = current and common.rounded(force.research_progress),
    queue = queue,
    available = available,
    triggers = triggers,
    researched = researched,
  }
end

function research.handlers.research(params)
  local player = common.get_player(params)
  local name = common.required_string(params, "technology")
  local force = player.force
  local technology = force.technologies[name]
  if not technology then
    common.fail("unknown technology: " .. name)
  end
  if technology.researched then
    common.fail(name .. " is already researched")
  end
  if technology.prototype.research_trigger then
    common.fail(name .. " is unlocked by its trigger, not by labs")
  end
  if not force.add_research(technology) then
    common.fail("could not queue " .. name .. "; check that its prerequisites are researched")
  end
  return research.state(force)
end

return research
