--- Image asset loader with safe fallbacks.
--- Replace PNGs under client/assets/ anytime; missing files use procedural draw.

local Assets = {
  tiles = {},
  heroes = {},
  enemies = {},
  ui = {},
  ready = false,
  missing = {},
}

local TILE_FILES = {
  [0] = "tiles/field.png",
  [1] = "tiles/wall.png",
  [2] = "tiles/town.png",
  [3] = "tiles/water.png",
  [4] = "tiles/dungeon.png",
}

local function try_image(path)
  if not love.filesystem.getInfo(path) then
    return nil
  end
  local ok, img = pcall(love.graphics.newImage, path)
  if ok and img then
    img:setFilter("nearest", "nearest")
    return img
  end
  return nil
end

function Assets.load()
  Assets.missing = {}
  for code, rel in pairs(TILE_FILES) do
    local path = "assets/" .. rel
    local img = try_image(path)
    Assets.tiles[code] = img
    if not img then
      Assets.missing[#Assets.missing + 1] = path
    end
  end

  Assets.heroes.local_p = try_image("assets/sprites/heroes/hero.png")
  Assets.heroes.battle = try_image("assets/sprites/heroes/hero_battle.png")
    or Assets.heroes.local_p
  Assets.heroes.other = try_image("assets/sprites/heroes/other.png")
    or Assets.heroes.local_p

  -- Preload common enemies; others load on demand
  Assets.enemies = {}
  Assets.ready = true
end

function Assets.tile(code)
  return Assets.tiles[code]
end

function Assets.hero(is_local)
  if is_local then
    return Assets.heroes.local_p
  end
  return Assets.heroes.other or Assets.heroes.local_p
end

function Assets.hero_battle()
  return Assets.heroes.battle or Assets.heroes.local_p
end

--- enemy_id from server (e.g. "slime", "red_slime")
function Assets.enemy(enemy_id)
  if not enemy_id then
    return nil
  end
  local id = tostring(enemy_id)
  if Assets.enemies[id] ~= nil then
    return Assets.enemies[id] or nil
  end
  local path = "assets/sprites/enemies/" .. id .. ".png"
  local img = try_image(path)
  -- cache misses as false so we don't hammer FS
  Assets.enemies[id] = img or false
  return img
end

function Assets.has_tiles()
  return Assets.tiles[0] ~= nil
end

return Assets
