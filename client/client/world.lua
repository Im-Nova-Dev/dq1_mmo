local World = {
  map = nil,
  width = 16,
  height = 12,
  tile_size = 40,
  players = {},
  local_player = nil,
}

-- fallback if server map not yet received
local DEFAULT_MAP = {
  {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1},
  {1,2,2,2,2,1,0,0,0,0,0,0,0,0,0,1},
  {1,2,2,2,2,1,0,0,0,0,0,0,0,0,0,1},
  {1,2,2,2,2,0,0,0,0,0,1,1,0,0,0,1},
  {1,2,2,2,2,0,0,0,0,0,1,1,0,0,0,1},
  {1,1,1,0,1,0,0,0,0,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,3,3,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,3,3,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,0,0,0,0,1,1,1,0,1},
  {1,0,0,0,0,0,0,0,0,0,0,1,0,0,0,1},
  {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1},
}

function World.reset()
  World.map = DEFAULT_MAP
  World.width = #DEFAULT_MAP[1]
  World.height = #DEFAULT_MAP
  World.players = {}
  World.local_player = nil
end

function World.set_map(map_data)
  if not map_data or not map_data.tiles then
    return
  end
  World.map = map_data.tiles
  World.width = map_data.width or #map_data.tiles[1]
  World.height = map_data.height or #map_data.tiles
end

function World.is_walkable(x, y)
  local row = World.map and World.map[y + 1]
  if not row then
    return false
  end
  local t = row[x + 1]
  return t == 0 or t == 2
end

function World.set_local(character)
  World.local_player = {
    id = character.id,
    name = character.name,
    x = math.floor(character.world_x or 2),
    y = math.floor(character.world_y or 2),
    level = character.level or 1,
  }
end

function World.set_players(list)
  World.players = {}
  for _, p in ipairs(list or {}) do
    World.players[p.id] = {
      id = p.id,
      name = p.name,
      x = math.floor(p.world_x or p.x or 0),
      y = math.floor(p.world_y or p.y or 0),
      level = p.level or 1,
    }
  end
end

function World.update_player(id, x, y)
  if World.local_player and World.local_player.id == id then
    World.local_player.x = x
    World.local_player.y = y
    return
  end
  local p = World.players[id]
  if p then
    p.x = x
    p.y = y
  else
    World.players[id] = { id = id, name = "P" .. tostring(id), x = x, y = y, level = 1 }
  end
end

function World.remove_player(id)
  World.players[id] = nil
end

World.reset()

return World
