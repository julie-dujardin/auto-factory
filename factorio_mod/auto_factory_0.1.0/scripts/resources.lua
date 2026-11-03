local common = require("scripts.common")

local resources = {handlers = {}}

local CHUNK_SIZE = 32

-- Kinds whose name contains fragment: resource entities, and the fluids offshore
-- pumps draw from tiles, such as water. Water bodies are traced along their shore
-- tiles: water tiles beside land, which form one 8-connected ring per shore.
local function kinds_matching(fragment)
  local kinds = {}
  local available = {}
  local resource_names = {}
  local shore_tiles = {}
  local shore_tile_names = {}
  for name, prototype in pairs(prototypes.entity) do
    if prototype.type == "resource" then
      available[name] = true
      if string.find(name, fragment, 1, true) then
        table.insert(resource_names, name)
        kinds[name] = {
          reach = prototype.resource_patch_search_radius,
          normal = prototype.infinite_resource and prototype.normal_resource_amount or nil,
        }
      end
    end
  end
  for name, prototype in pairs(prototypes.tile) do
    local fluid = prototype.fluid
    if fluid then
      available[fluid.name] = true
      if string.find(fluid.name, fragment, 1, true) then
        shore_tiles[name] = fluid.name
        table.insert(shore_tile_names, name)
        kinds[fluid.name] = {reach = 1, shore = true}
      end
    end
  end
  if next(kinds) == nil then
    local names = {}
    for name in pairs(available) do
      table.insert(names, name)
    end
    table.sort(names)
    common.fail("no resource name contains " .. fragment .. "; resources: " .. table.concat(names, ", "))
  end
  return {
    kinds = kinds,
    resource_names = resource_names,
    shore_tiles = shore_tiles,
    shore_tile_names = shore_tile_names,
  }
end

local function put(search, x, y, cell)
  local column = search.cells[x]
  if not column then
    column = {}
    search.cells[x] = column
  end
  if column[y] == nil then
    cell.x = x
    cell.y = y
    column[y] = cell
    table.insert(search.order, cell)
  end
end

local function load_shore(search, left, top)
  local surface = search.surface
  -- One tile of margin tells whether the chunk's border tiles touch land.
  local side = CHUNK_SIZE + 2
  local area = {{left - 1, top - 1}, {left + CHUNK_SIZE + 1, top + CHUNK_SIZE + 1}}
  local water = surface.count_tiles_filtered {area = area, name = search.shore_tile_names}
  if water == 0 or water == side * side then
    return
  end
  local fluids = {}
  for _, tile in pairs(surface.find_tiles_filtered {area = area, name = search.shore_tile_names}) do
    local position = tile.position
    fluids[position.x] = fluids[position.x] or {}
    fluids[position.x][position.y] = search.shore_tiles[tile.name]
  end
  for x = left, left + CHUNK_SIZE - 1 do
    local column = fluids[x]
    for y = top, top + CHUNK_SIZE - 1 do
      local fluid = column and column[y]
      if fluid and not (column[y - 1] and column[y + 1] and fluids[x - 1] and fluids[x - 1][y]
          and fluids[x + 1] and fluids[x + 1][y]) then
        put(search, x, y, {name = fluid})
      end
    end
  end
end

local function load_chunk(search, chunk)
  local left, top = chunk.x * CHUNK_SIZE, chunk.y * CHUNK_SIZE
  if #search.resource_names > 0 then
    local found = search.surface.find_entities_filtered {
      area = {{left, top}, {left + CHUNK_SIZE, top + CHUNK_SIZE}},
      type = "resource",
      name = search.resource_names,
    }
    for _, entity in pairs(found) do
      local position = entity.position
      put(search, math.floor(position.x), math.floor(position.y), {name = entity.name, amount = entity.amount})
    end
  end
  if #search.shore_tile_names > 0 then
    load_shore(search, left, top)
  end
end

local function cell_at(search, patch, x, y)
  local column = search.cells[x]
  local cell = column and column[y]
  if cell then
    return cell
  end
  local charted = search.charted[math.floor(x / CHUNK_SIZE)]
  if not (charted and charted[math.floor(y / CHUNK_SIZE)]) then
    patch.partial = true
  end
  return nil
end

-- Joins every cell of seed's kind within the kind's reach of the patch, as the map
-- does for its patch totals.
local function grow(search, seed)
  local kind = search.kinds[seed.name]
  local patch = {name = seed.name, cells = {seed}}
  seed.patch = patch
  local reach = kind.reach
  local index = 1
  while index <= #patch.cells do
    local cell = patch.cells[index]
    index = index + 1
    for x = cell.x - reach, cell.x + reach do
      for y = cell.y - reach, cell.y + reach do
        local other = cell_at(search, patch, x, y)
        if other and not other.patch and other.name == patch.name then
          other.patch = patch
          table.insert(patch.cells, other)
        end
      end
    end
  end
  return patch
end

local function center(cell)
  return {x = cell.x + 0.5, y = cell.y + 0.5}
end

local function summary(search, patch, origin)
  local kind = search.kinds[patch.name]
  local nearest, nearest_distance
  local amount = 0
  local left, top, right, bottom = math.huge, math.huge, -math.huge, -math.huge
  for _, cell in pairs(patch.cells) do
    local distance = common.distance_squared(origin, center(cell))
    if not nearest_distance or distance < nearest_distance then
      nearest, nearest_distance = cell, distance
    end
    amount = amount + (cell.amount or 0)
    left, right = math.min(left, cell.x), math.max(right, cell.x + 1)
    top, bottom = math.min(top, cell.y), math.max(bottom, cell.y + 1)
  end
  local entry = {
    name = patch.name,
    distance = common.rounded(math.sqrt(nearest_distance)),
    nearest = common.offset_from(origin, center(nearest)),
    partial = patch.partial,
  }
  if kind.shore then
    entry.coastline = #patch.cells
    return entry, nearest_distance
  end
  entry.tiles = #patch.cells
  if kind.normal then
    entry.yield_percent = math.floor(amount / kind.normal * 100 + 0.5)
  else
    entry.amount = amount
  end
  entry.area = {
    left_top = common.offset_from(origin, {x = left, y = top}),
    right_bottom = common.offset_from(origin, {x = right, y = bottom}),
  }
  return entry, nearest_distance
end

-- Searches the chunks the player's force has charted, as the map shows them.
function resources.handlers.resources(params)
  local player = common.get_player(params)
  local limit = math.max(1, math.min(50, math.floor(common.required_number(params, "limit"))))
  local search = kinds_matching(params.name or "")
  local surface = player.surface
  search.surface = surface
  search.cells = {}
  search.order = {}
  search.charted = {}

  for each in surface.get_chunks() do
    local chunk = {x = each.x, y = each.y}
    if player.force.is_chunk_charted(surface, chunk) and surface.is_chunk_generated(chunk) then
      search.charted[chunk.x] = search.charted[chunk.x] or {}
      search.charted[chunk.x][chunk.y] = true
      load_chunk(search, chunk)
    end
  end

  local origin = player.position
  local found = {}
  for _, cell in pairs(search.order) do
    if not cell.patch then
      local entry, distance = summary(search, grow(search, cell), origin)
      table.insert(found, {entry = entry, distance = distance})
    end
  end
  table.sort(found, function(a, b) return a.distance < b.distance end)
  local patches = {}
  for index = 1, math.min(limit, #found) do
    patches[index] = found[index].entry
  end
  return {patches = patches, omitted = #found - #patches}
end

return resources
