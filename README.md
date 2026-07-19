# Dragon Quest 1 MMO

<p align="center">
  <strong>Server-authoritative Dragon Quest I–style multiplayer</strong><br/>
  <code>Love2D</code> · <code>FastAPI</code> / WebSocket · <code>SQLite</code>
</p>

| Version | Status | Combat | Tests |
|:-------:|:------:|:------:|:------|
| **0.5.9** | Playable MVP | Server-side DQ1 | `cd server && python tests/run_tests.py` |

Shared overworld · classic combat · gear · **inn** · field magic · herbs & wings · global/nearby chat · emotes · live **online roster** · other players on the map.

---

## Contents

- [Look & art](#look--art)
- [Quick start](#quick-start)
- [Controls](#controls)
- [Features](#features)
- [Multiplayer testing](#multiplayer-testing)
- [Configuration](#configuration)
- [Layout](#layout)
- [Documentation](#documentation)
- [Networking](#networking)
- [Credits](#credits)

---

## Look & art

DQ-inspired UI + **swappable PNGs** in [`client/assets/`](client/assets/).

| Screen | Notes |
|:-------|:------|
| Login / heroes | Modals, hero cards |
| Overworld | Tiles, sprites, chat, minimap, online count |
| Combat | Enemy sprites, commands, log |
| Inventory | Gear, bag, shop, inn |

**Replace art:** [client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md)

| Path | Files |
|:-----|:------|
| `tiles/` | `field` `wall` `town` `water` `dungeon` |
| `sprites/heroes/` | `hero.png` `hero_battle.png` `other.png` |
| `sprites/enemies/` | `{enemy_id}.png` |

```bash
./tools/gen_placeholder_assets.sh
```

---

## Quick start

| Need | Notes |
|:-----|:------|
| Python **3.11+** | 3.12–3.14 OK |
| **Love2D 11.x** | Client |
| venv + pip | Server |

### Server

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

| | |
|:--|:--|
| OpenAPI | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |
| WebSocket | `ws://127.0.0.1:8000/ws` |

### Client

```bash
love client
```

1. Register → create a hero (gold + **3 herbs**)  
2. Enter World  
3. Town safe · **R** inn · **H** field heal · field/dungeon fights  

### Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
```

---

## Controls

| Key | Action |
|:----|:-------|
| **WASD** | Move |
| **T** / **Y** | Global / nearby chat |
| **E** | Wave emote |
| **R** | Inn rest (town) |
| **H** | Field Heal (if known) |
| **M** | Cycle field spells (Return, Repel, …) |
| **O** | Who online / nearby |
| **P** / **Tab** | Player list (+ who) |
| **C** | Toggle chat |
| **I** | Inventory / shop |
| **B** | Debug fight (`ALLOW_DEBUG`) |
| Combat **A** **F** **H** | Attack · Flee · Herb |
| Inv **Enter** **S** **U** | Use/equip · sell · unequip |
| **Esc** | Back / quit |

---

## Features

| Area | Details |
|:-----|:--------|
| **Auth** | Email/password + JWT · optional Google OAuth |
| **World** | Town · field · water · dungeon |
| **Inn** | Full HP/MP for gold (`level×4`, min 4) |
| **Field magic** | Heal, Return, Repel, Outside, Radiant (by level) |
| **Multiplayer** | Presence · AOI · ⚔ combat · live online pulse + roster |
| **Chat** | Global + nearby · rate-limited |
| **Emotes** | Nearby (wave, …) |
| **Combat** | DQ1 rules · herbs · 60s reconnect grace |
| **Items** | Gear · shop · herb · wings · fairy water |
| **Art** | Replaceable PNGs |
| **Resilience** | Prediction · heartbeats · free-port tests · dead-socket safe |

Defeat → town, half gold, partial HP.

---

## Multiplayer testing

```bash
./tools/mp_sim.sh
./tools/mp_sim.sh -n 5 --scenario wander --seconds 30
./tools/mp_love.sh 2
```

---

## Configuration

Optional [`.env.example`](.env.example) → `.env`:

`ENV` · `SECRET_KEY` · `DATABASE_URL` · `ALLOW_DEBUG` · `STARTING_GOLD` · `COMBAT_GRACE_SECONDS` · `GOOGLE_CLIENT_*` · `CORS_ORIGINS`

---

## Layout

```text
dq1_mmo/
├── README.md           # humans · GitHub
├── AGENTS.md           # coding agents / LLMs only
├── plan.md             # historical
├── docs/
│   ├── README.md       # docs index
│   └── HUMAN.md        # players & operators
├── client/             # Love2D + assets/
├── server/             # FastAPI + game
├── shared/             # dq1_data.json
└── tools/
```

---

## Documentation

Human and agent docs are **separate on purpose**.

| Audience | File | Contents |
|:---------|:-----|:---------|
| Everyone | [README.md](README.md) | Install, controls, features |
| Players / ops | [docs/HUMAN.md](docs/HUMAN.md) | Gameplay, inn, magic, hosting |
| Agents / LLMs | [AGENTS.md](AGENTS.md) | Protocol, hot paths, tests |
| Docs map | [docs/README.md](docs/README.md) | How to keep the split |
| Art | [client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md) | PNG names |
| History | [plan.md](plan.md) | Original plan — outdated |

> **Agents:** start at `AGENTS.md`. Protocol tables live there, not in this README.

---

## Networking

Server-authoritative moves · prediction · AOI · chat/emotes · inn · field magic · `who` / live `online` roster · combat reconnect.

Full message catalog → **[AGENTS.md](AGENTS.md)**.

---

## Credits

Inspired by **Dragon Quest I / Dragon Warrior** (NES-era math; not a ROM dump).  
Related: [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat). Fan project — not Square Enix.
