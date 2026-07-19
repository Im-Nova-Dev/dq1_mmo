--- HTTP helper: prefers luasocket, falls back to curl.

local Http = {}

local function trim(s)
  return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

function Http.encode_json(val)
  local t = type(val)
  if t == "nil" then
    return "null"
  elseif t == "boolean" then
    return val and "true" or "false"
  elseif t == "number" then
    return tostring(val)
  elseif t == "string" then
    return '"' .. val:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r") .. '"'
  elseif t == "table" then
    local is_array = #val > 0
    if is_array then
      local parts = {}
      for i = 1, #val do
        parts[i] = Http.encode_json(val[i])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      local parts = {}
      for k, v in pairs(val) do
        parts[#parts + 1] = Http.encode_json(tostring(k)) .. ":" .. Http.encode_json(v)
      end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  end
  error("cannot encode type " .. t)
end

function Http._json_to_lua(s)
  s = s:gsub("null", "nil")
  s = s:gsub('"([^"]+)"%s*:', '["%1"] =')
  s = s:gsub("%[", "{")
  s = s:gsub("%]", "}")
  return s
end

function Http.decode_json(str)
  if not str or str == "" then
    return nil, "empty"
  end
  local ok, json = pcall(require, "dkjson")
  if ok and json.decode then
    return json.decode(str)
  end
  local fn, err = load("return " .. Http._json_to_lua(str))
  if not fn then
    return nil, err
  end
  local ok2, result = pcall(fn)
  if not ok2 then
    return nil, result
  end
  return result
end

local function request_socket(method, url, body, headers)
  local ok_http, http = pcall(require, "socket.http")
  local ok_ltn12, ltn12 = pcall(require, "ltn12")
  if not ok_http or not ok_ltn12 then
    return nil, "no_socket"
  end
  headers = headers or {}
  local chunks = {}
  local req = {
    url = url,
    method = method,
    headers = headers,
    sink = ltn12.sink.table(chunks),
  }
  if body then
    req.source = ltn12.source.string(body)
    headers["Content-Length"] = tostring(#body)
    headers["Content-Type"] = headers["Content-Type"] or "application/json"
  end
  local _, code, res_headers = http.request(req)
  if not code then
    return nil, "request failed"
  end
  return {
    status = code,
    body = table.concat(chunks),
    headers = res_headers,
  }
end

local function shell_quote(s)
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

local function request_curl(method, url, body, headers)
  headers = headers or {}
  local cmd = { "curl", "-sS", "-X", method, url, "-w", "\n%{http_code}" }
  for k, v in pairs(headers) do
    cmd[#cmd + 1] = "-H"
    cmd[#cmd + 1] = k .. ": " .. v
  end
  if body then
    cmd[#cmd + 1] = "-H"
    cmd[#cmd + 1] = "Content-Type: application/json"
    cmd[#cmd + 1] = "--data-binary"
    cmd[#cmd + 1] = body
  end
  -- build safe command
  local parts = {}
  for i = 1, #cmd do
    parts[i] = shell_quote(cmd[i])
  end
  local handle = io.popen(table.concat(parts, " ") .. " 2>/dev/null")
  if not handle then
    return nil, "curl failed"
  end
  local out = handle:read("*a") or ""
  handle:close()
  local body_out, code = out:match("^(.*)\n(%d+)%s*$")
  if not code then
    return nil, "bad curl response"
  end
  return {
    status = tonumber(code),
    body = body_out or "",
    headers = {},
  }
end

function Http.request(method, url, body, headers)
  local res, err = request_socket(method, url, body, headers)
  if res then
    return res
  end
  if err == "no_socket" then
    return request_curl(method, url, body, headers)
  end
  -- socket present but failed — try curl
  local res2, err2 = request_curl(method, url, body, headers)
  if res2 then
    return res2
  end
  return nil, err or err2 or "http failed"
end

function Http.get(url, headers)
  return Http.request("GET", url, nil, headers)
end

function Http.post_json(url, data, headers)
  headers = headers or {}
  headers["Content-Type"] = "application/json"
  return Http.request("POST", url, Http.encode_json(data), headers)
end

return Http
