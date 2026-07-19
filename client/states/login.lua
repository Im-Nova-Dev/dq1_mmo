local Auth = require("client.auth")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")

local Login = {
  mode = "login",
  fields = {
    email = "hero@example.com",
    password = "password",
    username = "Hero",
  },
  focus = "email",
  order = { "email", "password", "username" },
  error = nil,
  status = nil,
  busy = false,
}

function Login:enter()
  self.error = nil
  self.busy = false
  self.status = "Server: " .. Session.server_http
end

function Login:leave() end
function Login:update(dt) end

function Login:draw()
  UI.draw_bg()
  local w, h = love.graphics.getDimensions()
  local pw = math.min(480, w - 40)
  local ph = self.mode == "register" and 460 or 400
  local px, py = (w - pw) / 2, (h - ph) / 2 - 10

  -- decorative outer frame
  UI.panel(px - 8, py - 8, pw + 16, ph + 16, { no_ornament = true })
  UI.panel(px, py, pw, ph, {
    title = "DRAGON QUEST 1 MMO",
    subtitle = "v0.5",
    title_h = 40,
    title_font = "body",
  })

  UI.subtitle(
    self.mode == "login" and "Welcome back, adventurer" or "Forge a new legend",
    px,
    py + 52,
    pw
  )

  local fx = px + 44
  local fy = py + 110
  local fw = pw - 88
  UI.field("Email", self.fields.email, fx, fy, fw, 36, self.focus == "email")
  UI.field(
    "Password",
    string.rep("•", #self.fields.password),
    fx,
    fy + 78,
    fw,
    36,
    self.focus == "password"
  )
  if self.mode == "register" then
    UI.field("Username", self.fields.username, fx, fy + 156, fw, 36, self.focus == "username")
  end

  local msg_y = py + ph - 128
  if self.error then
    UI.set_font("small")
    UI.color("danger")
    love.graphics.printf(tostring(self.error), px + 24, msg_y, pw - 48, "center")
  elseif self.status then
    UI.set_font("small")
    UI.color("ok")
    love.graphics.printf(self.status, px + 24, msg_y, pw - 48, "center")
  end

  local by = py + ph - 78
  local mx, my = UI.mouse()
  local b1 = { x = px + 40, y = by, w = 160, h = 42 }
  local b2 = { x = px + pw - 200, y = by, w = 160, h = 42 }
  local label1 = self.busy and "…" or (self.mode == "login" and "Login" or "Create")
  local label2 = self.mode == "login" and "Register" or "Back"
  UI.button(label1, b1.x, b1.y, b1.w, b1.h, UI.hit(mx, my, b1.x, b1.y, b1.w, b1.h), { primary = true })
  UI.button(label2, b2.x, b2.y, b2.w, b2.h, UI.hit(mx, my, b2.x, b2.y, b2.w, b2.h))

  UI.set_font("tiny")
  UI.color("muted")
  love.graphics.printf("Tab  fields   ·   Enter  submit", px, py + ph - 28, pw, "center")
  UI.reset_color()
end

function Login:_submit()
  if self.busy then
    return
  end
  self.error = nil
  self.busy = true
  self.status = "Contacting server…"

  local ok, err
  if self.mode == "login" then
    ok, err = Auth.login(self.fields.email, self.fields.password)
  else
    ok, err = Auth.register(self.fields.email, self.fields.password, self.fields.username)
  end
  self.busy = false
  if not ok then
    self.error = tostring(err or "request failed")
    self.status = "Server: " .. Session.server_http
    return
  end
  self.status = "Logged in as " .. tostring(Session.username)
  State.switch("character")
end

function Login:keypressed(key)
  if self.busy then
    return
  end
  if key == "tab" then
    local order = self.mode == "register" and self.order or { "email", "password" }
    local idx = 1
    for i, name in ipairs(order) do
      if name == self.focus then
        idx = i
        break
      end
    end
    self.focus = order[(idx % #order) + 1]
  elseif key == "return" or key == "kpenter" then
    self:_submit()
  elseif key == "backspace" then
    local v = self.fields[self.focus] or ""
    self.fields[self.focus] = v:sub(1, math.max(0, #v - 1))
  end
end

function Login:textinput(text)
  if self.busy or not self.focus then
    return
  end
  local v = self.fields[self.focus] or ""
  local max = self.focus == "password" and 72 or 64
  if #v < max then
    self.fields[self.focus] = v .. text
  end
end

function Login:mousepressed(x, y, button)
  if button ~= 1 or self.busy then
    return
  end
  local w, h = love.graphics.getDimensions()
  local pw = math.min(480, w - 40)
  local ph = self.mode == "register" and 460 or 400
  local px, py = (w - pw) / 2, (h - ph) / 2 - 10
  local fx = px + 44
  local fy = py + 110
  local fw = pw - 88
  if UI.hit(x, y, fx, fy, fw, 36) then
    self.focus = "email"
  elseif UI.hit(x, y, fx, fy + 78, fw, 36) then
    self.focus = "password"
  elseif self.mode == "register" and UI.hit(x, y, fx, fy + 156, fw, 36) then
    self.focus = "username"
  end

  local by = py + ph - 78
  local b1 = { x = px + 40, y = by, w = 160, h = 42 }
  local b2 = { x = px + pw - 200, y = by, w = 160, h = 42 }
  if UI.hit(x, y, b1.x, b1.y, b1.w, b1.h) then
    self:_submit()
  elseif UI.hit(x, y, b2.x, b2.y, b2.w, b2.h) then
    self.mode = self.mode == "login" and "register" or "login"
    self.error = nil
    self.status = "Server: " .. Session.server_http
  end
end

return Login
