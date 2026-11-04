local common = {}

local DIRECTIONS = {
  north = defines.direction.north,
  east = defines.direction.east,
  south = defines.direction.south,
  west = defines.direction.west,
}

common.DIRECTION_NAMES = {}
for name, value in pairs(defines.direction) do
  common.DIRECTION_NAMES[value] = name
end

function common.fail(message)
  error(message, 0)
end

function common.required_number(params, name)
  local value = tonumber(params[name])
  if value == nil then
    common.fail(name .. " must be a number")
  end
  return value
end

function common.required_string(params, name)
  local value = params[name]
  if type(value) ~= "string" or value == "" then
    common.fail(name .. " must be a non-empty string")
  end
  return value
end

function common.get_player(params)
  local player = nil
  if params.player_index then
    player = game.get_player(params.player_index)
  elseif params.player_name then
    player = game.get_player(params.player_name)
  elseif #game.connected_players > 0 then
    player = game.connected_players[1]
  elseif #game.players > 0 then
    player = game.players[1]
  end
  if not player or not player.valid then
    common.fail("no Factorio player is available")
  end
  if not player.character then
    common.fail("the selected player has no character")
  end
  return player
end

local function tile_centre(position)
  return {x = math.floor(position.x) + 0.5, y = math.floor(position.y) + 0.5}
end

-- Every position crossing the API is an offset from the centre of the tile the player
-- stood on when the harness last set the origin, once per run, so positions stay valid
-- as the player moves and 1x1 or odd-sized entities sit at whole offsets.
function common.set_origin(player)
  storage.origins = storage.origins or {}
  storage.origins[player.index] = tile_centre(player.position)
  return storage.origins[player.index]
end

function common.origin(player)
  return storage.origins and storage.origins[player.index] or common.set_origin(player)
end

-- The tile the player stands on.
function common.player_position(player)
  return common.offset_from(common.origin(player), tile_centre(player.position))
end

function common.position_from(player, params)
  local origin = common.origin(player)
  return {
    x = origin.x + common.required_number(params, "dx"),
    y = origin.y + common.required_number(params, "dy"),
  }
end

common.DIRECTION_STEPS = {
  [defines.direction.north] = {x = 0, y = -1},
  [defines.direction.east] = {x = 1, y = 0},
  [defines.direction.south] = {x = 0, y = 1},
  [defines.direction.west] = {x = -1, y = 0},
}

function common.direction_from(params, field)
  local name = common.required_string(params, field)
  local direction = DIRECTIONS[name]
  if not direction then
    common.fail(field .. " must be north, east, south, or west")
  end
  return direction
end

function common.distance_squared(first, second)
  local dx = first.x - second.x
  local dy = first.y - second.y
  return dx * dx + dy * dy
end

function common.rounded(value)
  return math.floor(value * 100 + 0.5) / 100
end

function common.plain_position(position)
  return {x = common.rounded(position.x), y = common.rounded(position.y)}
end

function common.offset_from(origin, position)
  return {
    dx = common.rounded(position.x - origin.x),
    dy = common.rounded(position.y - origin.y),
  }
end

function common.offset_text(origin, position)
  local offset = common.offset_from(origin, position)
  return "dx=" .. offset.dx .. " dy=" .. offset.dy
end

function common.nearest_first(list, position)
  table.sort(list, function(a, b)
    return common.distance_squared(position, a.position) < common.distance_squared(position, b.position)
  end)
  return list
end

return common
