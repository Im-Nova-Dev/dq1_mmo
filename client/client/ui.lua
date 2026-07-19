--- Shared DQ-style UI toolkit.

local UI = {
  fonts = {},
  theme = {
    bg = {0.06, 0.06, 0.12},
    panel = {0.08, 0.09, 0.16, 0.94},
    panel_inner = {0.05, 0.06, 0.11, 0.5},
    gold = {0.92, 0.82, 0.35},
    gold_dim = {0.65, 0.55, 0.25},
    text = {0.95, 0.93, 0.88},
    muted = {0.65, 0.68, 0.75},
    danger = {1.0, 0.38, 0.38},
    ok = {0.45, 0.9, 0.55},
    accent = {0.4, 0.65, 0.95},
    hp = {0.85, 0.22, 0.28},
    mp = {0.28, 0.48, 0.95},
    btn = {0.16, 0.15, 0.26},
    btn_hover = {0.32, 0.28, 0.14},
    local_p = {0.95, 0.85, 0.3},
    other_p = {0.4, 0.7, 1.0},
  },
  toasts = {},
}

function UI.init()
  UI.fonts.title = love.graphics.newFont(28)
  UI.fonts.large = love.graphics.newFont(20)
  UI.fonts.body = love.graphics.newFont(16)
  UI.fonts.small = love.graphics.newFont(13)
  UI.fonts.tiny = love.graphics.newFont(11)
  love.graphics.setFont(UI.fonts.body)
end

function UI.font(name)
  return UI.fonts[name] or UI.fonts.body
end

function UI.set_font(name)
  love.graphics.setFont(UI.font(name))
end

function UI.color(name, a)
  local c = UI.theme[name] or UI.theme.text
  love.graphics.setColor(c[1], c[2], c[3], a or c[4] or 1)
end

function UI.reset_color()
  love.graphics.setColor(1, 1, 1, 1)
end

function UI.draw_bg()
  local w, h = love.graphics.getDimensions()
  love.graphics.setColor(0.04, 0.05, 0.1)
  love.graphics.rectangle("fill", 0, 0, w, h)
  -- subtle vignette bands
  love.graphics.setColor(0.08, 0.07, 0.14, 0.35)
  love.graphics.rectangle("fill", 0, 0, w, 80)
  love.graphics.rectangle("fill", 0, h - 60, w, 60)
end

function UI.panel(x, y, w, h, opts)
  opts = opts or {}
  local r = opts.radius or 8
  -- shadow
  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.rectangle("fill", x + 3, y + 4, w, h, r, r)
  -- body
  UI.color("panel")
  love.graphics.rectangle("fill", x, y, w, h, r, r)
  -- inner
  love.graphics.setColor(0.04, 0.05, 0.1, 0.45)
  love.graphics.rectangle("fill", x + 4, y + 4, w - 8, h - 8, r - 2, r - 2)
  -- gold border double-line DQ style
  UI.color("gold")
  love.graphics.setLineWidth(2)
  love.graphics.rectangle("line", x, y, w, h, r, r)
  UI.color("gold_dim")
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", x + 3, y + 3, w - 6, h - 6, r - 1, r - 1)
  UI.reset_color()
end

function UI.button(label, x, y, w, h, hover, opts)
  opts = opts or {}
  if hover then
    UI.color("btn_hover")
  else
    UI.color("btn")
  end
  love.graphics.rectangle("fill", x, y, w, h, 5, 5)
  UI.color(hover and "gold" or "gold_dim")
  love.graphics.setLineWidth(2)
  love.graphics.rectangle("line", x, y, w, h, 5, 5)
  UI.set_font(opts.font or "body")
  UI.color("text")
  local font = love.graphics.getFont()
  love.graphics.print(label, x + (w - font:getWidth(label)) / 2, y + (h - font:getHeight()) / 2)
  UI.reset_color()
end

function UI.hit(mx, my, x, y, w, h)
  return mx >= x and mx <= x + w and my >= y and my <= y + h
end

function UI.field(label, value, x, y, w, h, focused)
  UI.set_font("small")
  UI.color("gold")
  love.graphics.print(label, x, y - 18)
  love.graphics.setColor(focused and 0.12 or 0.05, focused and 0.13 or 0.06, focused and 0.2 or 0.1, 1)
  love.graphics.rectangle("fill", x, y, w, h, 4, 4)
  UI.color(focused and "gold" or "gold_dim")
  love.graphics.setLineWidth(focused and 2 or 1)
  love.graphics.rectangle("line", x, y, w, h, 4, 4)
  UI.set_font("body")
  UI.color("text")
  local display = value or ""
  if focused and (math.floor(love.timer.getTime() * 2) % 2 == 0) then
    display = display .. "|"
  end
  love.graphics.print(display, x + 10, y + (h - love.graphics.getFont():getHeight()) / 2)
  UI.reset_color()
end

function UI.bar(x, y, w, h, ratio, fill_name, label)
  ratio = math.max(0, math.min(1, ratio or 0))
  love.graphics.setColor(0.12, 0.12, 0.16, 0.95)
  love.graphics.rectangle("fill", x, y, w, h, 3, 3)
  UI.color(fill_name or "hp")
  if ratio > 0 then
    love.graphics.rectangle("fill", x, y, math.max(2, w * ratio), h, 3, 3)
  end
  UI.color("gold_dim")
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", x, y, w, h, 3, 3)
  if label then
    UI.set_font("tiny")
    UI.color("text")
    local font = love.graphics.getFont()
    love.graphics.print(label, x + 4, y + (h - font:getHeight()) / 2)
  end
  UI.reset_color()
end

function UI.title(text, x, y, w)
  UI.set_font("title")
  UI.color("gold")
  if w then
    love.graphics.printf(text, x, y, w, "center")
  else
    love.graphics.print(text, x, y)
  end
  UI.reset_color()
end

function UI.text(text, x, y, style)
  style = style or "body"
  UI.set_font(style == "muted" and "small" or style)
  if style == "muted" then
    UI.color("muted")
  elseif style == "danger" then
    UI.color("danger")
  elseif style == "ok" then
    UI.color("ok")
  elseif style == "gold" then
    UI.color("gold")
  else
    UI.color("text")
  end
  love.graphics.print(text, x, y)
  UI.reset_color()
end

function UI.toast(message, kind, ttl)
  UI.toasts[#UI.toasts + 1] = {
    msg = tostring(message),
    kind = kind or "info",
    ttl = ttl or 3.5,
    age = 0,
  }
  while #UI.toasts > 6 do
    table.remove(UI.toasts, 1)
  end
end

function UI.update(dt)
  local i = 1
  while i <= #UI.toasts do
    local t = UI.toasts[i]
    t.age = t.age + dt
    if t.age >= t.ttl then
      table.remove(UI.toasts, i)
    else
      i = i + 1
    end
  end
end

function UI.draw_toasts()
  local w = love.graphics.getDimensions()
  local y = 16
  for i = #UI.toasts, 1, -1 do
    local t = UI.toasts[i]
    local alpha = 1
    if t.age > t.ttl - 0.6 then
      alpha = (t.ttl - t.age) / 0.6
    end
    UI.set_font("small")
    local font = love.graphics.getFont()
    local tw = font:getWidth(t.msg) + 24
    local th = font:getHeight() + 12
    local x = w - tw - 16
    love.graphics.setColor(0.05, 0.06, 0.12, 0.85 * alpha)
    love.graphics.rectangle("fill", x, y, tw, th, 6, 6)
    if t.kind == "join" then
      love.graphics.setColor(0.4, 0.85, 0.5, alpha)
    elseif t.kind == "leave" then
      love.graphics.setColor(0.95, 0.45, 0.4, alpha)
    elseif t.kind == "danger" then
      love.graphics.setColor(1, 0.4, 0.4, alpha)
    else
      love.graphics.setColor(0.9, 0.8, 0.4, alpha)
    end
    love.graphics.setLineWidth(1)
    love.graphics.rectangle("line", x, y, tw, th, 6, 6)
    love.graphics.setColor(1, 1, 1, alpha)
    love.graphics.print(t.msg, x + 12, y + 6)
    y = y + th + 6
  end
  UI.reset_color()
end

--- Nearby players list (multiplayer panel)
function UI.player_list(x, y, w, h, local_p, others, title)
  UI.panel(x, y, w, h)
  UI.set_font("small")
  UI.color("gold")
  love.graphics.print(title or "Online nearby", x + 12, y + 10)

  local row = y + 34
  UI.set_font("small")
  if local_p then
    love.graphics.setColor(0.25, 0.22, 0.12, 0.9)
    love.graphics.rectangle("fill", x + 8, row - 2, w - 16, 22, 3, 3)
    UI.color("local_p")
    love.graphics.circle("fill", x + 18, row + 9, 5)
    UI.color("text")
    love.graphics.print(
      string.format("%s  Lv%d  (you)", local_p.name or "You", local_p.level or 1),
      x + 30,
      row + 2
    )
    row = row + 26
  end

  local count = 0
  for _, p in pairs(others or {}) do
    count = count + 1
    if row + 22 > y + h - 10 then
      UI.color("muted")
      love.graphics.print("…", x + 30, row)
      break
    end
    UI.color("other_p")
    love.graphics.circle("fill", x + 18, row + 9, 5)
    UI.color("text")
    love.graphics.print(
      string.format("%s  Lv%d  (%d,%d)", p.name or "?", p.level or 1, math.floor((p.x or 0) + 0.01), math.floor((p.y or 0) + 0.01)),
      x + 30,
      row + 2
    )
    row = row + 24
  end
  if count == 0 then
    UI.color("muted")
    love.graphics.print("No other adventurers", x + 30, row + 2)
  end
  UI.reset_color()
end

--- Simple minimap
function UI.minimap(x, y, size, world)
  if not world or not world.map then
    return
  end
  local mw = world.width
  local mh = world.height
  local tw = size / mw
  local th = size / mh
  UI.panel(x - 4, y - 4, size + 8, size + 8, { radius = 4 })
  for j = 1, mh do
    for i = 1, mw do
      local tile = world.map[j][i]
      if tile == 1 then
        love.graphics.setColor(0.2, 0.18, 0.28)
      elseif tile == 2 then
        love.graphics.setColor(0.5, 0.42, 0.28)
      elseif tile == 3 then
        love.graphics.setColor(0.15, 0.3, 0.55)
      elseif tile == 4 then
        love.graphics.setColor(0.28, 0.2, 0.35)
      else
        love.graphics.setColor(0.18, 0.4, 0.22)
      end
      love.graphics.rectangle("fill", x + (i - 1) * tw, y + (j - 1) * th, tw + 0.5, th + 0.5)
    end
  end
  -- others
  for _, p in pairs(world.players or {}) do
    UI.color("other_p")
    love.graphics.circle("fill", x + (p.x + 0.5) * tw, y + (p.y + 0.5) * th, math.max(2, tw * 0.4))
  end
  if world.local_player then
    local lp = world.local_player
    UI.color("local_p")
    love.graphics.circle("fill", x + (lp.x + 0.5) * tw, y + (lp.y + 0.5) * th, math.max(2.5, tw * 0.45))
  end
  UI.reset_color()
end

return UI
