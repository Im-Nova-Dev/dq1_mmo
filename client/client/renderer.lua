local UI = require("client.ui")
local World = require("client.world")

local Renderer = {
  ox = 0,
  oy = 0,
  ts = 40,
}

local TILE = {
  [0] = {0.16, 0.40, 0.20}, -- field grass
  [1] = {0.22, 0.20, 0.32}, -- wall
  [2] = {0.48, 0.40, 0.28}, -- town
  [3] = {0.12, 0.28, 0.52}, -- water
  [4] = {0.20, 0.16, 0.26}, -- dungeon
}

local function checker(c, dark)
  return {
    c[1] * (dark and 0.85 or 1),
    c[2] * (dark and 0.85 or 1),
    c[3] * (dark and 0.85 or 1),
  }
end

function Renderer.layout()
  local ts = World.tile_size
  local map = World.map
  if not map then
    return 0, 0, ts
  end
  local map_w = World.width * ts
  local map_h = World.height * ts
  local sw, sh = love.graphics.getDimensions()
  local ox = math.floor((sw - map_w) / 2)
  local oy = math.floor((sh - map_h) / 2) + 24
  Renderer.ox, Renderer.oy, Renderer.ts = ox, oy, ts
  return ox, oy, ts
end

function Renderer.draw_overworld()
  local map = World.map
  if not map then
    return
  end
  local ox, oy, ts = Renderer.layout()

  -- ground
  for y = 1, #map do
    for x = 1, #map[y] do
      local tile = map[y][x]
      local px = ox + (x - 1) * ts
      local py = oy + (y - 1) * ts
      local base = TILE[tile] or TILE[0]
      local c = checker(base, (x + y) % 2 == 0)
      love.graphics.setColor(c)
      love.graphics.rectangle("fill", px, py, ts, ts)
      -- tile accents
      if tile == 2 then
        love.graphics.setColor(0.55, 0.45, 0.3, 0.35)
        love.graphics.rectangle("fill", px + 2, py + 2, ts - 4, ts - 4)
      elseif tile == 3 then
        love.graphics.setColor(0.3, 0.5, 0.8, 0.25)
        love.graphics.rectangle("fill", px, py + ts * 0.55, ts, ts * 0.2)
      elseif tile == 4 then
        love.graphics.setColor(0.35, 0.25, 0.4, 0.3)
        love.graphics.rectangle("line", px + 4, py + 4, ts - 8, ts - 8)
      elseif tile == 0 then
        love.graphics.setColor(0.25, 0.55, 0.28, 0.2)
        love.graphics.circle("fill", px + ts * 0.3, py + ts * 0.35, 2)
      end
      love.graphics.setColor(0, 0, 0, 0.18)
      love.graphics.rectangle("line", px, py, ts, ts)
    end
  end

  -- other players first
  for _, p in pairs(World.players) do
    Renderer.draw_actor(p, ox, oy, ts, false)
  end
  if World.local_player then
    Renderer.draw_actor(World.local_player, ox, oy, ts, true)
  end

  love.graphics.setColor(1, 1, 1, 1)
  return ox, oy, ts
end

function Renderer.draw_actor(p, ox, oy, ts, is_local)
  local px = ox + p.x * ts + ts / 2
  local py = oy + p.y * ts + ts / 2
  local body = is_local and UI.theme.local_p or UI.theme.other_p
  local r = ts * 0.30

  -- shadow
  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.ellipse("fill", px, py + r * 0.85, r * 0.85, r * 0.35)

  -- body
  love.graphics.setColor(body[1], body[2], body[3], 1)
  love.graphics.circle("fill", px, py, r)
  -- outline
  love.graphics.setColor(0, 0, 0, 0.9)
  love.graphics.setLineWidth(2)
  love.graphics.circle("line", px, py, r)
  -- head highlight
  love.graphics.setColor(1, 1, 1, 0.25)
  love.graphics.circle("fill", px - r * 0.25, py - r * 0.3, r * 0.28)

  -- nameplate
  local name = p.name or "?"
  local lv = p.level or 1
  local label = string.format("%s  Lv%d", name, lv)
  if is_local then
    label = label .. " ★"
  end
  UI.set_font("tiny")
  local font = love.graphics.getFont()
  local tw = font:getWidth(label) + 10
  local th = font:getHeight() + 4
  local nx = px - tw / 2
  local ny = py - r - th - 4
  love.graphics.setColor(0.05, 0.05, 0.1, 0.8)
  love.graphics.rectangle("fill", nx, ny, tw, th, 3, 3)
  if is_local then
    love.graphics.setColor(UI.theme.gold[1], UI.theme.gold[2], UI.theme.gold[3], 0.9)
  else
    love.graphics.setColor(UI.theme.other_p[1], UI.theme.other_p[2], UI.theme.other_p[3], 0.9)
  end
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", nx, ny, tw, th, 3, 3)
  love.graphics.setColor(1, 1, 1, 1)
  love.graphics.print(label, nx + 5, ny + 2)
end

return Renderer
