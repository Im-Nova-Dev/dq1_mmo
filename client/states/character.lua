local Auth = require("client.auth")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")

local Character = {
  list = {},
  selected = 1,
  creating = false,
  confirm_delete = false,
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
  self.status = "Loading characters…"
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
  UI.draw_bg()
  local w, h = love.graphics.getDimensions()
  local pw = math.min(540, w - 40)
  local ph = 480
  local px, py = (w - pw) / 2, (h - ph) / 2

  UI.panel(px, py, pw, ph, {
    title = "Select Hero",
    subtitle = tostring(Session.username or "Account"),
    title_h = 38,
  })

  if self.creating then
    UI.subtitle("Name your champion", px, py + 58, pw)
    UI.field("Hero name", self.new_name, px + 48, py + 140, pw - 96, 38, true)
    UI.set_font("tiny")
    UI.color("muted")
    love.graphics.printf("2–16 letters, numbers, spaces", px, py + 195, pw, "center")
  else
    if #self.list == 0 then
      UI.set_font("body")
      UI.color("muted")
      love.graphics.printf("Create a hero to begin your quest.", px + 40, py + 180, pw - 80, "center")
    end
    for i, c in ipairs(self.list) do
      local y = py + 78 + (i - 1) * 72
      local selected = i == self.selected
      local hp = tonumber(c.current_hp) or 0
      local mhp = math.max(1, tonumber(c.max_hp) or 1)
      UI.list_row(
        px + 36,
        y,
        pw - 72,
        62,
        selected,
        c.name,
        string.format("%s G", tostring(c.gold or "0")),
        {
          sub = string.format("Lv %d   HP %d/%d", c.level or 1, hp, mhp),
        }
      )
      -- mini HP bar on card
      UI.bar(px + 64, y + 42, 160, 8, hp / mhp, "hp")
    end
  end

  local mx, my = UI.mouse()
  local by = py + ph - 78
  if self.creating then
    UI.button(
      self.busy and "…" or "Create",
      px + 40,
      by,
      160,
      42,
      UI.hit(mx, my, px + 40, by, 160, 42),
      { primary = true }
    )
    UI.button("Cancel", px + pw - 200, by, 160, 42, UI.hit(mx, my, px + pw - 200, by, 160, 42))
  else
    UI.button(
      self.busy and "…" or "Enter World",
      px + 40,
      by,
      160,
      42,
      UI.hit(mx, my, px + 40, by, 160, 42),
      { primary = true }
    )
    UI.button("New Hero", px + pw - 200, by, 160, 42, UI.hit(mx, my, px + pw - 200, by, 160, 42))
  end

  local msg_y = py + ph - 112
  if self.error then
    UI.set_font("small")
    UI.color("danger")
    love.graphics.printf(tostring(self.error), px + 20, msg_y, pw - 40, "center")
  elseif self.status then
    UI.set_font("small")
    UI.color("ok")
    love.graphics.printf(self.status, px + 20, msg_y, pw - 40, "center")
  end

  UI.set_font("tiny")
  UI.color("muted")
  if self.confirm_delete then
    love.graphics.printf("Delete this hero?  Y yes  ·  N cancel", px, py + ph - 28, pw, "center")
  else
    love.graphics.printf(
      "↑↓ select  ·  Enter world  ·  N new  ·  D delete  ·  Esc logout",
      px,
      py + ph - 28,
      pw,
      "center"
    )
  end
  UI.reset_color()
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

function Character:_delete()
  if self.busy then
    return
  end
  local c = self.list[self.selected]
  if not c then
    self.error = "No hero selected"
    self.confirm_delete = false
    return
  end
  self.error = nil
  self.busy = true
  local ok, err = Auth.delete_character(c.id)
  self.busy = false
  self.confirm_delete = false
  if not ok then
    self.error = tostring(err or "delete failed")
    return
  end
  self.status = "Deleted " .. tostring(c.name)
  self:_reload()
end

function Character:keypressed(key)
  if self.busy then
    return
  end
  if self.confirm_delete then
    if key == "y" then
      self:_delete()
    elseif key == "n" or key == "escape" then
      self.confirm_delete = false
      self.status = "Delete cancelled"
    end
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
  elseif key == "d" then
    if not self.list[self.selected] then
      self.error = "No hero to delete"
    else
      self.confirm_delete = true
      self.error = nil
      self.status = "Confirm delete: " .. tostring(self.list[self.selected].name)
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
  local pw = math.min(540, w - 40)
  local ph = 480
  local px, py = (w - pw) / 2, (h - ph) / 2
  local by = py + ph - 78

  if not self.creating then
    for i = 1, #self.list do
      local ly = py + 78 + (i - 1) * 72
      if UI.hit(x, y, px + 36, ly, pw - 72, 62) then
        if self.selected == i then
          self:_enter_world()
        else
          self.selected = i
        end
      end
    end
  end

  if self.creating then
    if UI.hit(x, y, px + 40, by, 160, 42) then
      self:_create()
    elseif UI.hit(x, y, px + pw - 200, by, 160, 42) then
      self.creating = false
      self.error = nil
    end
  else
    if UI.hit(x, y, px + 40, by, 160, 42) then
      self:_enter_world()
    elseif UI.hit(x, y, px + pw - 200, by, 160, 42) then
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
