local Http = require("client.http")
local Session = require("client.session")

local Auth = {}

local function auth_header()
  return { Authorization = "Bearer " .. (Session.token or "") }
end

local function parse_fail(res, fallback)
  local data = Http.decode_json(res.body)
  local detail = data and data.detail or fallback
  return nil, Http.format_error(detail)
end

local function trim(s)
  return (tostring(s or ""):gsub("^%s+", ""):gsub("%s+$", ""))
end

function Auth.validate_register(email, password, username)
  email = trim(email):lower()
  username = trim(username)
  if email == "" or not email:find("@") then
    return nil, "Enter a valid email"
  end
  if #password < 6 then
    return nil, "Password must be at least 6 characters"
  end
  if #password > 72 then
    return nil, "Password too long"
  end
  if #username < 2 then
    return nil, "Username must be at least 2 characters"
  end
  if not username:match("^[A-Za-z0-9_%-]+$") then
    return nil, "Username: letters, numbers, _ or - only"
  end
  return true
end

function Auth.validate_login(email, password)
  email = trim(email)
  if email == "" or not email:find("@") then
    return nil, "Enter a valid email"
  end
  if password == "" then
    return nil, "Enter your password"
  end
  return true
end

function Auth.validate_character_name(name)
  name = trim(name)
  name = name:gsub("%s+", " ")
  if #name < 2 then
    return nil, "Name must be at least 2 characters"
  end
  if #name > 16 then
    return nil, "Name too long (max 16)"
  end
  if not name:match("^[A-Za-z0-9_%- ]+$") then
    return nil, "Name: letters, numbers, spaces, _ or - only"
  end
  return name
end

function Auth.register(email, password, username)
  email = trim(email):lower()
  username = trim(username)
  local ok, err = Auth.validate_register(email, password, username)
  if not ok then
    return nil, err
  end

  local res, req_err = Http.post_json(Session.server_http .. "/auth/register", {
    email = email,
    password = password,
    username = username,
  })
  if not res then
    return nil, req_err or "Cannot reach server — is it running?"
  end
  if res.status == 0 or res.status == nil then
    return nil, "Cannot reach server — is it running?"
  end
  if res.status ~= 201 then
    return parse_fail(res, "register failed: " .. tostring(res.status))
  end
  local data = Http.decode_json(res.body)
  if not data or not data.access_token then
    return nil, "bad register response"
  end
  Session.token = data.access_token
  Session.user_id = data.user_id
  Session.username = data.username
  return data
end

function Auth.login(email, password)
  email = trim(email):lower()
  local ok, err = Auth.validate_login(email, password)
  if not ok then
    return nil, err
  end

  local res, req_err = Http.post_json(Session.server_http .. "/auth/login", {
    email = email,
    password = password,
  })
  if not res then
    return nil, req_err or "Cannot reach server — is it running?"
  end
  if res.status ~= 200 then
    return parse_fail(res, "login failed: " .. tostring(res.status))
  end
  local data = Http.decode_json(res.body)
  if not data or not data.access_token then
    return nil, "bad login response"
  end
  Session.token = data.access_token
  Session.user_id = data.user_id
  Session.username = data.username
  return data
end

function Auth.list_characters()
  if not Session.token then
    return nil, "Not logged in"
  end
  local res, err = Http.get(Session.server_http .. "/auth/characters", auth_header())
  if not res then
    return nil, err or "Cannot reach server"
  end
  if res.status == 401 then
    return nil, "Session expired — log in again"
  end
  if res.status ~= 200 then
    return parse_fail(res, "list characters failed")
  end
  local data = Http.decode_json(res.body)
  if type(data) ~= "table" then
    return nil, "bad characters response"
  end
  -- ensure array-like
  if data.id and not data[1] then
    return { data }
  end
  return data
end

function Auth.create_character(name)
  local clean, err = Auth.validate_character_name(name)
  if not clean then
    return nil, err
  end
  if not Session.token then
    return nil, "Not logged in"
  end
  local res, req_err = Http.post_json(
    Session.server_http .. "/auth/characters",
    { name = clean },
    auth_header()
  )
  if not res then
    return nil, req_err or "Cannot reach server"
  end
  if res.status ~= 201 then
    return parse_fail(res, "create character failed")
  end
  local data = Http.decode_json(res.body)
  if not data or not data.id then
    return nil, "bad create response"
  end
  return data
end

function Auth.delete_character(character_id)
  if not Session.token then
    return nil, "Not logged in"
  end
  if not character_id then
    return nil, "No hero selected"
  end
  local res, err = Http.request(
    "DELETE",
    Session.server_http .. "/auth/characters/" .. tostring(character_id),
    nil,
    auth_header()
  )
  if not res then
    return nil, err or "Cannot reach server"
  end
  if res.status == 401 then
    return nil, "Session expired — log in again"
  end
  if res.status == 404 then
    return nil, "Hero not found"
  end
  if res.status ~= 204 and res.status ~= 200 then
    return parse_fail(res, "delete failed: " .. tostring(res.status))
  end
  return true
end

return Auth
