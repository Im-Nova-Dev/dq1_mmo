local Assets = require("client.assets")
local UI = require("client.ui")
local World = require("client.world")

local Renderer = {
  ox = 0,
  oy = 0,
  ts = 40,
}

local TILE = {
  [0] = {0.18, 0.44, 0.24}, -- field grass
  [1] = {0.20, 0.18, 0.30}, -- wall
  [2] = {0.52, 0.42, 0.30}, -- town
  [3] = {0.14, 0.32, 0.56}, -- water
  [4] = {0.22, 0.16, 0.28}, -- dungeon
}

local function checker(c, dark)
  local m = dark and 0.82 or 1.05
  return { c[1] * m, c[2] * m, c[3] * m }
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
  local oy = math.floor((sh - map_h) / 2) + 10
  Renderer.ox, Renderer.oy, Renderer.ts = ox, oy, ts
  return ox, oy, ts
end

local function draw_tile_fallback(tile, px, py, ts, x, y)
  local base = TILE[tile] or TILE[0]
  local c = checker(base, (x + y) % 2 == 0)
  love.graphics.setColor(c)
  love.graphics.rectangle("fill", px, py, ts, ts)
  if tile == 2 then
    love.graphics.setColor(0.62, 0.50, 0.34, 0.35)
    love.graphics.rectangle("fill", px + 3, py + 3, ts - 6, ts - 6)
  elseif tile == 3 then
    local wave = math.sin((UI._t or 0) * 2 + x * 0.7 + y) * 2
    love.graphics.setColor(0.35, 0.55, 0.85, 0.3)
    love.graphics.rectangle("fill", px, py + ts * 0.5 + wave, ts, ts * 0.18)
  elseif tile == 4 then
    love.graphics.setColor(0.4, 0.28, 0.48, 0.25)
    love.graphics.rectangle("line", px + 5, py + 5, ts - 10, ts - 10)
  elseif tile == 0 then
    love.graphics.setColor(0.3, 0.6, 0.32, 0.25)
    love.graphics.circle("fill", px + ts * 0.3, py + ts * 0.35, 2.5)
  elseif tile == 1 then
    love.graphics.setColor(0.12, 0.1, 0.18, 0.5)
    love.graphics.rectangle("fill", px + 2, py + 2, ts - 4, ts - 4)
  end
  love.graphics.setColor(0, 0, 0, 0.12)
  love.graphics.rectangle("line", px, py, ts, ts)
end

function Renderer.draw_overworld()
  local map = World.map
  if not map then
    return
  end
  local ox, oy, ts = Renderer.layout()

  -- map shadow plate
  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.rectangle("fill", ox + 6, oy + 8, World.width * ts, World.height * ts, 4, 4)

  -- gold frame around map
  love.graphics.setColor(0.05, 0.05, 0.1, 0.9)
  love.graphics.rectangle("fill", ox - 6, oy - 6, World.width * ts + 12, World.height * ts + 12, 4, 4)
  UI.color("gold_dim")
  love.graphics.setLineWidth(2)
  love.graphics.rectangle("line", ox - 6, oy - 6, World.width * ts + 12, World.height * ts + 12, 4, 4)

  for y = 1, #map do
    for x = 1, #map[y] do
      local tile = map[y][x]
      local px = ox + (x - 1) * ts
      local py = oy + (y - 1) * ts
      local img = Assets.tile(tile)
      if img then
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.draw(img, px, py, 0, ts / img:getWidth(), ts / img:getHeight())
        -- subtle grid
        love.graphics.setColor(0, 0, 0, 0.08)
        love.graphics.rectangle("line", px, py, ts, ts)
      else
        draw_tile_fallback(tile, px, py, ts, x, y)
      end
    end
  end

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
  local bob = is_local and math.sin((UI._t or 0) * 3) * 1.2 or 0
  local img = Assets.hero(is_local)

  -- shadow
  love.graphics.setColor(0, 0, 0, 0.4)
  love.graphics.ellipse("fill", px, py + ts * 0.28, ts * 0.22, ts * 0.08)

  if p.in_combat then
    love.graphics.setColor(1, 0.35, 0.3, 0.4 + 0.15 * math.sin((UI._t or 0) * 5))
    love.graphics.setLineWidth(3)
    love.graphics.circle("line", px, py + bob, ts * 0.32)
  end

  if img then
    local scale = (ts * 0.85) / math.max(img:getWidth(), img:getHeight())
    local iw, ih = img:getWidth() * scale, img:getHeight() * scale
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(img, px - iw / 2, py + bob - ih * 0.55, 0, scale, scale)
  else
    -- procedural fallback
    local body = is_local and UI.theme.local_p or UI.theme.other_p
    if p.in_combat and not is_local then
      body = UI.theme.danger
    end
    local r = ts * 0.30
    love.graphics.setColor(body[1], body[2], body[3], 1)
    love.graphics.circle("fill", px, py + bob, r)
    love.graphics.setColor(0, 0, 0, 0.85)
    love.graphics.setLineWidth(2)
    love.graphics.circle("line", px, py + bob, r)
  end

  local name = p.name or "?"
  local lv = p.level or 1
  local label = string.format("%s  Lv%d", name, lv)
  if is_local then
    label = label .. " ★"
  end
  if p.in_combat then
    label = label .. " ⚔"
  end
  UI.set_font("tiny")
  local font = love.graphics.getFont()
  local tw = font:getWidth(label) + 12
  local th = font:getHeight() + 6
  local nx = px - tw / 2
  local ny = py + bob - ts * 0.55 - th
  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.rectangle("fill", nx + 1, ny + 2, tw, th, 3, 3)
  love.graphics.setColor(0.05, 0.05, 0.1, 0.88)
  love.graphics.rectangle("fill", nx, ny, tw, th, 3, 3)
  if p.in_combat then
    love.graphics.setColor(UI.theme.danger[1], UI.theme.danger[2], UI.theme.danger[3], 0.95)
  elseif is_local then
    love.graphics.setColor(UI.theme.gold[1], UI.theme.gold[2], UI.theme.gold[3], 0.95)
  else
    love.graphics.setColor(UI.theme.other_p[1], UI.theme.other_p[2], UI.theme.other_p[3], 0.95)
  end
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", nx, ny, tw, th, 3, 3)
  love.graphics.setColor(1, 1, 1, 1)
  love.graphics.print(label, nx + 6, ny + 3)
end

return Renderer
