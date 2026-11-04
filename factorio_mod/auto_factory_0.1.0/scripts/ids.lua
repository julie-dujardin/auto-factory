local common = require("scripts.common")

local ids = {handlers = {}}

local PROTOTYPE_KINDS = {item = true, fluid = true, recipe = true, entity = true, technology = true}
-- Technologies are searched by api_technologies.
local KINDS = {"item", "fluid", "recipe", "entity", "entity_type", "status"}
local SEARCHABLE = {}
for _, kind in pairs(KINDS) do
  SEARCHABLE[kind] = true
end
local SEARCH_LIMIT = 10
local SIMILAR_LIMIT = 8

-- False for entities the player cannot select, such as corpses and explosions.
function ids.selectable(prototype)
  local box = prototype.selection_box
  return prototype.selectable_in_game and box.left_top.x < box.right_bottom.x
end

-- Hidden recipes and recycling (Space Age), which only undoes crafts, are never listed.
function ids.listed_recipe(prototype)
  if prototype.hidden then
    return false
  end
  for _, category in pairs(prototype.categories) do
    if category == "recycling" then
      return false
    end
  end
  return true
end

-- Hidden prototypes, unlisted recipes, and unselectable entities are valid IDs but
-- never suggested.
local function suggested(kind, prototype)
  if kind == "recipe" then
    return ids.listed_recipe(prototype)
  end
  if prototype.hidden then
    return false
  end
  return kind ~= "entity" or ids.selectable(prototype)
end

local function names(kind, everything)
  local result = {}
  if PROTOTYPE_KINDS[kind] then
    for name, prototype in pairs(prototypes[kind]) do
      if everything or suggested(kind, prototype) then
        table.insert(result, name)
      end
    end
  elseif kind == "entity_type" then
    local seen = {}
    for _, prototype in pairs(prototypes.entity) do
      if not seen[prototype.type] and (everything or suggested("entity", prototype)) then
        seen[prototype.type] = true
        table.insert(result, prototype.type)
      end
    end
  else
    for name in pairs(defines.entity_status) do
      table.insert(result, name)
    end
  end
  return result
end

local function exists(kind, name)
  if PROTOTYPE_KINDS[kind] then
    return prototypes[kind][name] ~= nil
  end
  for _, candidate in pairs(names(kind, true)) do
    if candidate == name then
      return true
    end
  end
  return false
end

local function edit_distance(a, b)
  local previous = {}
  for j = 0, #b do
    previous[j] = j
  end
  for i = 1, #a do
    local current = {[0] = i}
    local byte = a:byte(i)
    for j = 1, #b do
      local cost = byte == b:byte(j) and 0 or 1
      current[j] = math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
    end
    previous = current
  end
  return previous[#b]
end

-- The candidates resembling query, best first. Each query word scores 2 when it is a
-- whole word of the ID and 1 when it is part of one; ties go to fewer edits. An ID
-- matching no word is kept only as a likely typo.
function ids.ranked(query, candidates)
  query = string.lower(query)
  local words = {}
  for word in string.gmatch(query, "[^%s%-_]+") do
    table.insert(words, word)
  end
  local typos = math.max(1, math.floor(#query / 4))
  local ranked = {}
  for _, name in pairs(candidates) do
    local parts = {}
    for part in string.gmatch(name, "[^%-_]+") do
      parts[part] = true
    end
    local score = 0
    for _, word in pairs(words) do
      if parts[word] then
        score = score + 2
      elseif string.find(name, word, 1, true) then
        score = score + 1
      end
    end
    local edits = edit_distance(query, name)
    if score > 0 or edits <= typos then
      table.insert(ranked, {name = name, score = score, edits = edits})
    end
  end
  table.sort(ranked, function(a, b)
    if a.score ~= b.score then
      return a.score > b.score
    end
    if a.edits ~= b.edits then
      return a.edits < b.edits
    end
    return a.name < b.name
  end)
  local result = {}
  for index, each in ipairs(ranked) do
    result[index] = each.name
  end
  return result
end

local function closest(query, kinds, limit)
  local candidates = {}
  local seen = {}
  for _, kind in pairs(kinds) do
    for _, name in pairs(names(kind)) do
      if not seen[name] then
        seen[name] = true
        table.insert(candidates, name)
      end
    end
  end
  local result = ids.ranked(query, candidates)
  for index = limit + 1, #result do
    result[index] = nil
  end
  return result
end

-- Returns name when it is an ID of one of the kinds, else fails listing similar IDs.
function ids.check(name, ...)
  local kinds = {...}
  for _, kind in pairs(kinds) do
    if exists(kind, name) then
      return name
    end
  end
  local label = (string.gsub(table.concat(kinds, " or "), "_", " "))
  local similar = closest(name, kinds, SIMILAR_LIMIT)
  if #similar == 0 then
    local finder = kinds[1] == "technology" and "api_technologies" or "api_search"
    common.fail("unknown " .. label .. ": " .. name .. "; find the ID with " .. finder)
  end
  common.fail("unknown " .. label .. ": " .. name .. "; similar: " .. table.concat(similar, ", "))
end

function ids.handlers.search(params)
  local query = common.required_string(params, "query")
  local kind = params.kind or "any"
  local kinds = KINDS
  if kind ~= "any" then
    kinds = {kind}
    if not SEARCHABLE[kind] then
      common.fail("kind must be any or one of " .. table.concat(KINDS, ", "))
    end
  end
  local result = {}
  local found = false
  for _, each in pairs(kinds) do
    local matches = closest(query, {each}, SEARCH_LIMIT)
    if #matches > 0 then
      result[each] = matches
      found = true
    end
  end
  if not found then
    common.fail("no ID resembles " .. query)
  end
  return result
end

return ids
