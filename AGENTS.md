# AGENTS.md — LLM / agent contract for `dq1_mmo`

You are editing this multiplayer game. Prefer this file over guessing.  
For human-oriented prose, see [docs/HUMAN.md](docs/HUMAN.md) and the root [README.md](README.md).

## Scope

| In (current) | Out (do not invent as done) |
|:-------------|:----------------------------|
| Love2D client + FastAPI WS server | Parties / PvP / trade |
| Server-authoritative DQ1 1v1 combat | Idle offline progress |
| Grid overworld, AOI presence, global chat | Multi-map worlds |
| Auth JWT, equipment, shop, XP, DQ-style UI | Pixel art / full sprite pipeline (assets empty) |
| SQLite persistence | Binary protocol |

**Version:** `0.5.2` (`server/config.py` → `VERSION`)

## Documentation map (do not mix)

| File | Audience | Use for |
|:-----|:---------|:--------|
| `README.md` | Humans on GitHub | Run instructions, features, controls |
| `docs/HUMAN.md` | Humans | Gameplay & ops detail |
| `docs/README.md` | Both | Index + audience rules |
| `AGENTS.md` | **You (agents)** | Protocol, paths, tests, constraints |
| `plan.md` | Historical | Original roadmap only — **not source of truth** |

**Never** put long protocol tables or “do not invent” lists only in `README.md` / `docs/HUMAN.md`.  
**Never** put “how to install Love2D for players” only in this file.

When you change behavior, update **README + HUMAN + this file** as needed.

## Install / run (agent checklist)

```bash
# Server
cd server && source .venv/bin/activate   # create venv + pip install -r requirements.txt if needed
./run.sh                                 # :8000

# Tests (required after game logic / network changes)
python tests/run_tests.py

# Client (host machine with Love2D)
love client

# Multiplayer bots
./tools/mp_sim.sh -n 3
```

Env: optional repo-root `.env` (see `.env.example`). Isolated tests set `DATABASE_URL` / `ALLOW_DEBUG` themselves.

## Architecture (authoritative model)

```
Love2D client  --JSON WebSocket-->  FastAPI
   states/*                         network/message_handler.py
   client/network.lua               network/websocket_manager.py  (AOI, rates)
                                    game/combat_engine.py         (DQ1 1v1)
                                    game/world_manager.py         (MVP_MAP)
                                    SQLite via database/*
```

- **Combat is server-side only.** Client sends actions; never trust client HP/damage.
- Client `libs/dq1-combat` is a **symlink for reference** — live multiplayer does **not** resolve battles in Lua.
- Canonical data: `shared/dq1_data.json` (loaded by Python `game/data_loader.py`). Tiny `shared/*.lua` stubs are not the authority.

## Hot paths (edit carefully)

| Path | Role |
|:-----|:-----|
| `server/main.py` | WS accept loop, connect meta, send |
| `server/network/message_handler.py` | All game messages + combat + chat |
| `server/network/websocket_manager.py` | Connections, AOI, move/chat rate limits |
| `server/network/protocol.py` | Message type enums |
| `server/network/presence.py` | Position flush, idle kick, combat grace expiry |
| `server/game/combat_engine.py` | Battle state machine |
| `server/game/formulas.py` | Damage / flee / magic math |
| `server/game/world_manager.py` | Map tiles & zones |
| `client/client/ui.lua` | Shared DQ-style UI toolkit (panels, bars, menus) |
| `client/client/renderer.lua` | Overworld tiles + actors |
| `client/client/network.lua` | WS client, reconnect, `Network.chat` |
| `client/client/world.lua` | Prediction queue, remote players |
| `client/states/login.lua` | Auth UI |
| `client/states/character.lua` | Hero select / create UI |
| `client/states/overworld.lua` | Move, chat UI, presence handlers |
| `client/states/combat.lua` | Combat UI only (no authority) |
| `client/states/inventory.lua` | Bag / equip / shop UI |
| `client/conf.lua` | Window title/size (default 1024×720) |

UI presentation changes stay in `client/client/ui.lua` + states; do not fork styling per-screen unless necessary.

## WebSocket protocol

All messages are JSON objects with a `type` string.

### Client → server

| type | Fields (main) | Notes |
|:-----|:--------------|:------|
| `auth` | `token`, `character_id` | First message after connect |
| `move` | `x`, `y`, `seq` | Adjacent step only; rate-limited |
| `attack` / `flee` / `use_spell` | spell: `spell` or `id` | Only in combat, hero turn |
| `equip` / `unequip` | `slot`, `item` | Not in combat |
| `buy` / `sell` / `shop` / `inventory` | `item` | Shop only in **town** |
| `use_item` | `item` / `item_id` | Herb (heal), Wings (town), Fairy Water (repel 64 steps). Herb OK in combat (uses turn). |
| `chat` / `say` | `text` (or `message`/`msg`) | Global; max 200; ~0.75s rate |
| `ping` | `t`, optional `sync` | Heartbeat / presence refresh |
| `sync` | — | Full nearby snapshot |
| `debug_encounter` | `enemy`, optional `seed` | Only if `ALLOW_DEBUG` |

### Server → client

| type | Purpose |
|:-----|:--------|
| `auth_ok` / `auth_fail` | Session |
| `world_state` | `players`, `map`, optional `you`, `online` |
| `move_ok` | Ack: `ok`, `x`, `y`, `seq`, optional `duplicate`/`reason` |
| `player_joined` / `player_left` / `player_moved` | Presence |
| `player_update` | `level`, `in_combat`, position |
| `chat` | `player_id`, `name`, `text`, `channel` (`global`) |
| `combat_start` / `combat_resume` / `combat_update` / `combat_end` | Battles |
| `level_up` | After victory |
| `inventory_update` / `shop_list` | Economy |
| `item_used` | Consumable result (`healed`, `teleported`, `repel_steps`, `message`) |
| `error` | `reason` (+ sometimes `x`/`y`/`seq`/`retry_after`) |
| `pong` | Echo `t` for RTT |

Public player objects include: `id`, `name`, `x`/`y` (and `world_x`/`world_y`), `level`, `in_combat`, `map_id`.

### Reliability rules (do not break)

1. Moves are **server-authoritative**; client predicts with `seq` and reconciles on `move_ok`.
2. Duplicate `seq` → idempotent `move_ok` with `duplicate: true`.
3. Reconnect: only the **current** WebSocket may `disconnect` that character (`manager.owns`).
4. Combat disconnect → grace (`COMBAT_GRACE_SECONDS`); resume via `combat_resume`.
5. Idle kick: `disconnect()` already notifies AOI — **do not** global double-broadcast `player_left`.
6. Chat: sanitize (strip control chars, collapse whitespace); empty → error; rate-limit → `chat_rate_limit`.

## Tests (mandatory for your changes)

```bash
cd server && source .venv/bin/activate && python tests/run_tests.py
```

| Module | What it proves |
|:-------|:---------------|
| `tests.test_formulas` | Damage / flee / hurt bands |
| `tests.test_combat` | Battle flow, gear ATK, level-up |
| `tests.test_presence` | AOI, reconnect ownership, rates, combat meta |
| `tests.test_api` | Register → WS move → buy → equip → fight |
| `tests.test_multiplayer` | Two clients, chat, combat flag, leave |
| `tests.test_adversarial` | Edge cases: world, combat, gold, chat |
| `tests.test_items` | Herb / wings / fairy water / repel |

- Prefer **adding tests** for new multiplayer/network behavior.
- Use isolated `DATABASE_URL` (runner already temp-isolates).
- Do not depend on the developer's live `data/dq1_mmo.db`.

## Coding conventions

- Python: async FastAPI; game logic in `server/game/*`; no combat authority in the client.
- Lua: Love2D 11; states under `client/states/`; network thin; UI via `UI.*` helpers.
- Bump `VERSION` in `server/config.py` when shipping user-visible behavior; mirror in README + HUMAN.
- Gold may be string-stored (big-number ready); HP/damage still normal ints for MVP.
- Client assets under `client/assets/` are empty — use procedural renderer/UI until art lands.
- Do not commit secrets; never force-push `main` unless user asks.

## Common agent mistakes

| Mistake | Correct approach |
|:--------|:-----------------|
| Run combat in Lua client for multiplayer | Call server actions only |
| Trust client position | Validate adjacency + walkable tiles |
| Update only README | Keep `AGENTS.md` / `docs/HUMAN.md` in sync |
| Treat `plan.md` as backlog truth | Re-read code + this file |
| Skip multiplayer tests after net changes | Run full `run_tests.py` |

## Related libraries

- Combat reference (Lua): sibling repo / `client/libs/dq1-combat` → see that repo's `AGENTS.md` and `docs/HUMAN.md`.
- Live MMO combat code lives in **Python** under `server/game/`.
