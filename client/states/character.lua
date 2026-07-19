local Auth = require("client.auth")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")

local Character = {
  list = {},
  selected = 1,
  creating = false,
  new_name = "Solo",
  error = nil,
  status = "Loading...",
  busy = false,
}

function Character:enter()
  self.error = nil
  self.creating = false
  self.busy = false
  self:_reload()
end

function Character:_reload()
  self.status = "Loading characters..."
  local list, err = Auth.list_characters()
  if not list then
    self.error = tostring(err or "failed")
    self.list = {}
    self.status = nil
    return
  end
  self.list = list
  self.selected = math.min(math.max(1, self.selected), math.max(1, #list))
  self.status = #list == 0 and "No heroes yet — create one" or (#list .. " / 3 heroes")
end

function Character:leave() end
function Character:update(dt) end

function Character:draw()
  if UI.draw_bg then
    UI.draw_bg()
  else
    love.graphics.clear(0.05, 0.05, 0.09)
  end
  local w, h = love.graphics.getDimensions()
  local pw, ph = 500, 440
  local px, py = (w - pw) / 2, (h - ph) / 2
  UI.panel(px, py, pw, ph)

  love.graphics.setColor(1, 0.92, 0.45)
  love.graphics.printf("Select Hero", px, py + 18, pw, "center")
  love.graphics.setColor(0.7, 0.75, 0.8)
  love.graphics.printf("Account: " .. tostring(Session.username or "?"), px, py + 48, pw, "center")

  if self.creating then
    UI.field("Hero name", self.new_name, px + 40, py + 130, pw - 80, 34, true)
    love.graphics.setColor(0.55, 0.6, 0.65)
    love.graphics.printf("2–16 letters, numbers, spaces", px, py + 175, pw, "center")
  else
    if #self.list == 0 then
      love.graphics.setColor(0.6, 0.65, 0.7)
      love.graphics.printf("Create a hero to begin your quest.", px + 40, py + 160, pw - 80, "center")
    end
    for i, c in ipairs(self.list) do
      local y = py + 95 + (i - 1) * 56
      local selected = i == self.selected
      if selected then
        love.graphics.setColor(0.32, 0.28, 0.14, 1)
      else
        love.graphics.setColor(0.1, 0.11, 0.18, 1)
      end
      love.graphics.rectangle("fill", px + 36, y, pw - 72, 48, 6, 6)
      love.graphics.setColor(selected and 0.95 or 0.55, selected and 0.85 or 0.5, 0.35, 1)
      love.graphics.setLineWidth(2)
      love.graphics.rectangle("line", px + 36, y, pw - 72, 48, 6, 6)
      love.graphics.setColor(1, 1, 0.92)
      love.graphics.print(c.name, px + 52, y + 8)
      love.graphics.setColor(0.7, 0.75, 0.8)
      love.graphics.print(
        string.format("Lv %d   HP %d/%d   %s G", c.level, c.current_hp, c.max_hp, tostring(c.gold or "0")),
        px + 52,
        y + 28
      )
    end
  end

  local mx, my = love.mouse.getPosition()
  local by = py + ph - 72
  if self.creating then
    UI.button(self.busy and "..." or "Create", px + 40, by, 150, 40, UI.hit(mx, my, px + 40, by, 150, 40))
    UI.button("Cancel", px + pw - 190, by, 150, 40, UI.hit(mx, my, px + pw - 190, by, 150, 40))
  else
    UI.button(
      self.busy and "..." or "Enter World",
      px + 40,
      by,
      150,
      40,
      UI.hit(mx, my, px + 40, by, 150, 40)
    )
    UI.button("New Hero", px + pw - 190, by, 150, 40, UI.hit(mx, my, px + pw - 190, by, 150, 40))
  end

  if self.error then
    love.graphics.setColor(1, 0.4, 0.4)
    love.graphics.printf(tostring(self.error), px + 20, py + ph - 110, pw - 40, "center")
  elseif self.status then
    love.graphics.setColor(0.55, 0.85, 0.6)
    love.graphics.printf(self.status, px + 20, py + ph - 110, pw - 40, "center")
  end
  love.graphics.setColor(1, 1, 1)
end

function Character:_enter_world()
  if self.busy then
    return
  end
  local c = self.list[self.selected]
  if not c then
    self.error = "Create a hero first"
    return
  end
  Session.character = c
  State.switch("overworld")
end

function Character:_create()
  if self.busy then
    return
  end
  self.error = nil
  self.busy = true
  local c, err = Auth.create_character(self.new_name)
  self.busy = false
  if not c then
    self.error = tostring(err or "create failed")
    return
  end
  self.creating = false
  self:_reload()
  for i, ch in ipairs(self.list) do
    if ch.id == c.id then
      self.selected = i
      break
    end
  end
  self.status = "Created " .. tostring(c.name)
end

function Character:keypressed(key)
  if self.busy then
    return
  end
  if self.creating then
    if key == "backspace" then
      self.new_name = self.new_name:sub(1, math.max(0, #self.new_name - 1))
    elseif key == "return" then
      self:_create()
    elseif key == "escape" then
      self.creating = false
      self.error = nil
    end
    return
  end
  if key == "up" then
    self.selected = math.max(1, self.selected - 1)
  elseif key == "down" then
    self.selected = math.min(#self.list, self.selected + 1)
  elseif key == "return" then
    self:_enter_world()
  elseif key == "n" then
    if #self.list >= 3 then
      self.error = "Maximum 3 heroes per account"
    else
      self.creating = true
      self.error = nil
      self.new_name = "Solo"
    end
  elseif key == "escape" then
    Session.token = nil
    State.switch("login")
  end
end

function Character:textinput(text)
  if self.creating and not self.busy and #self.new_name < 16 then
    self.new_name = self.new_name .. text
  end
end

function Character:mousepressed(x, y, button)
  if button ~= 1 or self.busy then
    return
  end
  local w, h = love.graphics.getDimensions()
  local pw, ph = 500, 440
  local px, py = (w - pw) / 2, (h - ph) / 2
  local by = py + ph - 72

  if not self.creating then
    for i = 1, #self.list do
      local ly = py + 95 + (i - 1) * 56
      if UI.hit(x, y, px + 36, ly, pw - 72, 48) then
        self.selected = i
      end
    end
  end

  if self.creating then
    if UI.hit(x, y, px + 40, by, 150, 40) then
      self:_create()
    elseif UI.hit(x, y, px + pw - 190, by, 150, 40) then
      self.creating = false
      self.error = nil
    end
  else
    if UI.hit(x, y, px + 40, by, 150, 40) then
      self:_enter_world()
    elseif UI.hit(x, y, px + pw - 190, by, 150, 40) then
      if #self.list >= 3 then
        self.error = "Maximum 3 heroes per account"
      else
        self.creating = true
        self.error = nil
        self.new_name = "Solo"
      end
    end
  end
end

return Character
