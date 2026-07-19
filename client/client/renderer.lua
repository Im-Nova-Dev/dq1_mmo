local World = require("client.world")

local Renderer = {}

local COLORS = {
  [0] = {0.18, 0.42, 0.22}, -- grass
  [1] = {0.25, 0.22, 0.35}, -- wall
  [2] = {0.45, 0.40, 0.28}, -- town
  [3] = {0.15, 0.28, 0.55}, -- water
  grid = {0, 0, 0, 0.25},
  local_p = {0.95, 0.85, 0.25},
  other_p = {0.35, 0.65, 0.95},
}

function Renderer.draw_overworld()
  local ts = World.tile_size
  local map = World.map
  if not map then
    return
  end

  local map_w = World.width * ts
  local map_h = World.height * ts
  local sw, sh = love.graphics.getDimensions()
  local ox = math.floor((sw - map_w) / 2)
  local oy = math.floor((sh - map_h) / 2) + 10

  for y = 1, #map do
    for x = 1, #map[y] do
      local tile = map[y][x]
      local px = ox + (x - 1) * ts
      local py = oy + (y - 1) * ts
      local c = COLORS[tile] or COLORS[0]
      love.graphics.setColor(c)
      love.graphics.rectangle("fill", px, py, ts, ts)
      love.graphics.setColor(COLORS.grid)
      love.graphics.rectangle("line", px, py, ts, ts)
    end
  end

  for _, p in pairs(World.players) do
    Renderer._draw_player(p, ox, oy, ts, COLORS.other_p)
  end

  if World.local_player then
    Renderer._draw_player(World.local_player, ox, oy, ts, COLORS.local_p)
  end

  love.graphics.setColor(1, 1, 1, 1)
  return ox, oy
end

function Renderer._draw_player(p, ox, oy, ts, color)
  local px = ox + p.x * ts + ts / 2
  local py = oy + p.y * ts + ts / 2
  love.graphics.setColor(color)
  love.graphics.circle("fill", px, py, ts * 0.28)
  love.graphics.setColor(0, 0, 0, 0.85)
  love.graphics.setLineWidth(2)
  love.graphics.circle("line", px, py, ts * 0.28)
  love.graphics.setColor(1, 1, 1, 1)
  local label = p.name or "?"
  local font = love.graphics.getFont()
  love.graphics.print(label, px - font:getWidth(label) / 2, py - ts * 0.55)
end

return Renderer
