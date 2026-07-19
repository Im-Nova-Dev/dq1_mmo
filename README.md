# Dragon Quest 1 MMO

> Server-authoritative **Dragon Quest I–style** multiplayer  
> **Love2D** client · **FastAPI / WebSocket** server · **SQLite**

| | |
|:--|:--|
| **Version** | `0.5.1` |
| **Status** | Playable MVP |
| **Combat** | Server-side DQ1 rules |
| **Client** | Love2D 11.x · 1024×720 default |
| **Tests** | `cd server && python tests/run_tests.py` |

Walk a shared overworld, fight random encounters with classic Dragon Quest combat math, equip gear, shop in town, chat globally, and see other adventurers nearby.

---

## Table of contents

- [Screenshots / look](#screenshots--look)
- [Quick start](#quick-start)
- [Controls](#controls)
- [Features](#features)
- [Multiplayer testing](#multiplayer-testing)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Documentation](#documentation)
- [Networking](#networking)
- [License / credits](#license--credits)

---

## Screenshots / look

The client uses a **Dragon Quest–inspired UI toolkit** (gold double-frame windows, starfield menus, HP/MP bars, combat command menus). Map tiles and actors are procedural (no sprite pack yet).

| Screen | Notes |
|:-------|:------|
| Login / Register | Centered modal, tab fields |
| Hero select | Cards with level, HP bar, gold |
| Overworld | HUD, minimap, chat, nearby list |
| Combat | Arena, command list, battle log |
| Inventory / Shop | Equipment panel + bag list |

---

## Quick start

### Requirements

| Need | Notes |
|:-----|:------|
| **Python 3.11+** | 3.12–3.14 fine |
| **Love2D 11.x** | Client only |
| **pip / venv** | Server deps |

### 1. Server

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
./run.sh
```

| Endpoint | URL |
|:---------|:----|
| OpenAPI | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |
| WebSocket | `ws://127.0.0.1:8000/ws` |

### 2. Client

```bash
# from repo root
love client
```

1. **Register** (any email / password / username)  
2. **Create a hero** (or pick an existing one — double-click works)  
3. **Enter World** — you spawn in town (safe)

> Demo fields often pre-filled: `hero@example.com` / `password` — you still need to register once.

### 3. Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
```

Suites: formulas · combat · presence/AOI · full API flow · two-player multiplayer (chat, combat flag).

---

## Controls

| Key | Action |
|:----|:-------|
| **WASD** / arrows | Move on the grid |
| **T** | Chat · **Enter** send · **Esc** cancel |
| **C** | Toggle chat panel |
| **I** | Inventory / town shop (**Tab** switches shop) |
| **P** / **Tab** | Nearby player list |
| **B** | Debug slime fight (`ALLOW_DEBUG=1`) |
| Combat **↑↓** · **Enter** | Menu |
| Combat **A** / **F** | Attack / Flee |
| Inventory **S** / **U** | Sell / unequip |
| **Esc** | Back · logout · or quit from overworld |

---

## Features

| Area | Details |
|:-----|:--------|
| **Auth** | Email/password + JWT · optional Google OAuth |
| **World** | Town (safe) · field · water · dungeon |
| **UI** | DQ-style panels, menus, HUD, combat/inventory screens |
| **Multiplayer** | Nearby presence · AOI join/leave · ⚔ combat status |
| **Chat** | Global · sanitized · rate-limited |
| **Combat** | Attack / spells / flee · enemy AI · level-ups |
| **Items** | Weapon / armor / shield / helmet · town shop |
| **Resilience** | Move prediction · heartbeats · 60s combat reconnect |

Defeat → town respawn, half gold, partial HP (XP kept).

---

## Multiplayer testing

### Bot simulator

```bash
./tools/mp_sim.sh                              # 3 bots, meet in town
./tools/mp_sim.sh -n 5 --scenario wander --seconds 30
./tools/mp_sim.sh -n 2 --scenario aoi --seconds 45
./tools/mp_sim.sh -n 2 -i                      # interactive
```

Interactive: `status`, `move 0 e`, `wander`, `meet`, `sync`, `quit`.

### Two game windows

```bash
# terminal 1
cd server && source .venv/bin/activate && ./run.sh

# terminal 2
./tools/mp_love.sh 2    # register two different accounts
```

---

## Configuration

Copy [`.env.example`](.env.example) → `.env` at the **repo root** (optional).

| Variable | Purpose | Default / notes |
|:---------|:--------|:----------------|
| `ENV` | `development` / `production` | Prod refuses default secrets |
| `SECRET_KEY` | JWT signing | **Required** in production |
| `DATABASE_URL` | SQLite file | `data/dq1_mmo.db` |
| `ALLOW_DEBUG` | Debug encounters | On in dev, off in prod |
| `STARTING_GOLD` | New heroes | `300` |
| `COMBAT_GRACE_SECONDS` | Mid-fight reconnect | `60` |
| `GOOGLE_CLIENT_*` | OAuth | Optional |
| `CORS_ORIGINS` | CORS | Use real origins in prod |

---

## Project layout

```text
dq1_mmo/
├── README.md              # ← humans (GitHub landing)
├── AGENTS.md              # ← coding agents / LLMs only
├── plan.md                # historical roadmap (not live truth)
├── docs/
│   ├── README.md          # docs index + audience rules
│   └── HUMAN.md           # player & operator guide
├── client/                # Love2D game
│   ├── client/ui.lua      # shared DQ-style UI toolkit
│   ├── client/renderer.lua
│   ├── states/            # login, character, overworld, combat, inventory
│   └── libs/              # websocket + dq1-combat symlink (reference)
├── server/                # FastAPI + combat + presence
├── shared/                # dq1_data.json (canonical catalogs)
├── tools/                 # mp_sim, multi-window helpers
└── data/                  # SQLite (gitignored)
```

---

## Documentation

Human docs and agent docs are **intentionally separate**.

| Audience | Start here | Contains |
|:---------|:-----------|:---------|
| **Players & operators** | [docs/HUMAN.md](docs/HUMAN.md) | Gameplay, zones, hosting |
| **GitHub / newcomers** | [README.md](README.md) | Install, controls, features |
| **Agents / LLMs** | [AGENTS.md](AGENTS.md) | Protocol, hot paths, tests, constraints |
| **Docs map** | [docs/README.md](docs/README.md) | How to keep this split clean |
| **History only** | [plan.md](plan.md) | Original multi-phase plan — may be outdated |

> **Agents:** read `AGENTS.md` first. Do not treat `plan.md` as the current design.

---

## Networking

- Server-authoritative moves (`seq` + `move_ok`)
- Client prediction + reconciliation
- Rate limits: moves, messages, chat
- Heartbeats, ~90s idle kick, deferred position saves
- Presence AOI (~10 tiles); `in_combat` on nearby players

Full message catalog → **[AGENTS.md](AGENTS.md)**.

---

## License / credits

- Combat design inspired by **Dragon Quest I / Dragon Warrior** (NES-era math; not a ROM dump).
- Server combat is a Python port aligned with [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat) (optional symlink under `client/libs/dq1-combat`).
- Fan / experimental project — not affiliated with Square Enix.
