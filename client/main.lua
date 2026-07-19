local src = love.filesystem.getSource()
package.path = src .. "/?.lua;" .. src .. "/?/init.lua;" .. src .. "/libs/?.lua;" .. package.path

local State = require("client.state")
local UI = require("client.ui")

local states = {
  login = require("states.login"),
  character = require("states.character"),
  overworld = require("states.overworld"),
  combat = require("states.combat"),
  inventory = require("states.inventory"),
}

function love.load()
  love.graphics.setDefaultFilter("nearest", "nearest")
  love.keyboard.setKeyRepeat(true)
  math.randomseed(os.time())
  UI.init()
  State.register(states)
  State.switch("login")
end

function love.update(dt)
  UI.update(dt)
  State.update(dt)
end

function love.draw()
  State.draw()
  UI.draw_toasts()
end

function love.keypressed(key, scancode, isrepeat)
  State.keypressed(key, scancode, isrepeat)
end

function love.textinput(text)
  State.textinput(text)
end

function love.mousepressed(x, y, button)
  State.mousepressed(x, y, button)
end
