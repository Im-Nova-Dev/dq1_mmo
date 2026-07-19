# Dragon Quest 1 MMO

<p align="center">
  <b>Server-authoritative Dragon Quest&nbsp;I–style multiplayer</b><br/>
  <sub>Love2D&nbsp;·&nbsp;FastAPI / WebSocket&nbsp;·&nbsp;SQLite</sub>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.5.15-7c3aed?style=for-the-badge" />
  <img alt="status" src="https://img.shields.io/badge/status-playable_MVP-16a34a?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/tests-90_passing-059669?style=for-the-badge" />
</p>

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img alt="love2d" src="https://img.shields.io/badge/Love2D-11.x-EA316E?style=flat-square" />
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-WebSocket-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img alt="license" src="https://img.shields.io/badge/fan_project-not_Square_Enix-6b7280?style=flat-square" />
</p>

Share one overworld with other heroes. Explore **town**, **field**, and **dungeon**. Fight classic 1v1 battles. Rest at the **inn**, cast **field magic** (including **Radiant** light), shop for gear, and chat — global, nearby, or private **whisper**.

> **Fan project.** Inspired by *Dragon Quest I / Dragon Warrior*. Not affiliated with Square Enix.

---

## Contents

| Section | |
|:--------|:--|
| [Highlights](#highlights) | What ships in the MVP |
| [Quick start](#quick-start) | Server · client · tests |
| [Controls](#controls) | Keyboard reference |
| [Look & art](#look--art) | Swappable sprites |
| [Multiplayer tools](#multiplayer-tools) | Local bots & dual windows |
| [Configuration](#configuration) | Env vars & production |
| [Project layout](#project-layout) | Repo map |
| [Documentation](#documentation) | **Humans vs agents** |
| [Credits](#credits) | Attribution |

---

## Highlights

| | |
|:--|:--|
| **World** | Shared grid · safe **town** · field encounters · **dungeon** |
| **Combat** | Server-side DQ1 rules · attack / magic / flee / herbs · ~60s reconnect grace |
| **Town** | Inn rest · shop · equip · **sell equipped gear** |
| **Magic** | Heal · Return · **Repel** · **Radiant** (dungeon light) · Outside · battle spells by level |
| **Social** | Global & nearby chat · **/w whisper** · emotes · **look (L)** · online roster *(no map radar)* |
| **Heroes** | Up to 3 per account · create / **delete** · XP progress on status sheet |
| **Items** | Herb · wings · fairy water · weapons & armor |
| **HUD** | HP/MP · gold · nearby/online · **repel N** · **light N** · status sheet (**F**) |
| **Art** | Drop-in PNGs · Kenney CC0 tiles/heroes · enemy sprites |

**Not in the MVP:** parties · PvP · trade · quests · multi-map worlds.

---

## Quick start

| Need | Notes |
|:-----|:------|
| **Python 3.11+** | 3.12–3.14 OK |
| **Love2D 11.x** | Game client |
| Port **8000** | Default (configurable) |

### 1 · Server

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
./run.sh
```

| Service | URL |
|:--------|:----|
| OpenAPI | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |
| WebSocket | `ws://127.0.0.1:8000/ws` |

### 2 · Client

```bash
love client
```

1. **Register** → create a hero (gold + **3 herbs**)
2. Hero select: **N** new · **D** delete (**Y** confirm) · max **3** heroes
3. **Enter World** — spawn in town (safe)
4. **R** inn · **I** bag/shop · field for fights · **F** status

### 3 · Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
# expect: 90 passed
```

---

## Controls

<details open>
<summary><b>Overworld</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **WASD** | Move |
| **T** / **Y** | Global / nearby chat |
| **/w Name msg** | Whisper (also `/tell`) while chat is open |
| **E** | Cycle emotes |
| **F** | Status sheet (stats, gear, EXP to next, spells) |
| **R** | Inn rest *(town)* |
| **H** / **M** | Field Heal · cycle field spells |
| **K** | List known spells |
| **O** | Who’s online / nearby |
| **L** | Look / examine a nearby (or roster) player |
| **P** / **Tab** | Toggle player list |
| **C** | Toggle chat |
| **I** | Inventory / shop |
| **B** | Debug slime fight *(if `ALLOW_DEBUG=1`)* |
| **Esc** | Disconnect & quit |

</details>

<details>
<summary><b>Combat</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **↑ ↓** · **Enter** | Menu |
| **A** / **F** / **H** | Attack · Flee · Herb |

</details>

<details>
<summary><b>Inventory</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **Enter** | Use / equip |
| **S** / **U** | Sell · unequip |
| **R** | Inn *(town)* |
| **Tab** | Shop list *(town)* |

</details>

<details>
<summary><b>Hero select</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **↑ ↓** | Select hero |
| **Enter** | Enter world |
| **N** | New hero |
| **D** then **Y** | Delete hero |
| **Esc** | Log out |

</details>

Full player guide → **[docs/HUMAN.md](docs/HUMAN.md)**

---

## Look & art

DQ-inspired UI. Drop PNGs into [`client/assets/`](client/assets/) — **filenames matter**.

| Path | Files |
|:-----|:------|
| `tiles/` | `field` · `wall` · `town` · `water` · `dungeon` |
| `sprites/heroes/` | `hero.png` · `hero_battle.png` · `other.png` |
| `sprites/enemies/` | `{enemy_id}.png` e.g. `slime.png` |
| `src/kenney/` | 16×16 CC0 masters (optional regen) |

Tiles / heroes / UI: **[Kenney](https://kenney.nl) CC0** (replace freely). Enemies: project SVG→PNG.

```bash
./tools/gen_placeholder_assets.sh
```

Licenses & names → **[client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md)**

---

## Multiplayer tools

```bash
./tools/mp_sim.sh                                    # headless bots
./tools/mp_sim.sh -n 5 --scenario wander --seconds 30
./tools/mp_love.sh 2                                 # two Love2D windows
```

---

## Configuration

Optional: copy [`.env.example`](.env.example) → `.env`

| Variable | Purpose |
|:---------|:--------|
| `ENV` | `development` / `production` |
| `SECRET_KEY` | JWT signing — strong secret in prod |
| `DATABASE_URL` | SQLite path |
| `ALLOW_DEBUG` | `1` enables debug encounters (**B**) |
| `STARTING_GOLD` | New hero gold |
| `COMBAT_GRACE_SECONDS` | Mid-battle reconnect window |
| `GOOGLE_CLIENT_*` | Optional Google OAuth |
| `CORS_ORIGINS` | Browser CORS allow-list |

**Production:** strong `SECRET_KEY` · `ENV=production` · `ALLOW_DEBUG=0` · durable DB · tight CORS.

---

## Project layout

```text
dq1_mmo/
├── README.md              ← humans / GitHub (this file)
├── AGENTS.md              ← coding agents & LLMs only
├── plan.md                ← historical roadmap (not live truth)
├── docs/
│   ├── README.md          ← docs map & audience rules
│   └── HUMAN.md           ← players & operators
├── client/                ← Love2D + assets
├── server/                ← FastAPI, combat, WebSocket
├── shared/                ← dq1_data.json (canonical game data)
└── tools/                 ← multiplayer sims, asset gen
```

---

## Documentation

Human docs and agent/LLM docs are **intentionally separate**.

| Audience | Document | Contents |
|:---------|:---------|:---------|
| **Everyone** | [README.md](README.md) | Install · features · controls |
| **Players / ops** | [docs/HUMAN.md](docs/HUMAN.md) | Gameplay · inn · magic · social · hosting |
| **Coding agents** | [AGENTS.md](AGENTS.md) | Protocol · hot paths · tests · reliability |
| **Docs map** | [docs/README.md](docs/README.md) | How to keep the split clean |
| **Artists** | [client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md) | PNG names & licenses |
| **History** | [plan.md](plan.md) | Original plan — may be outdated |

```text
┌─────────────┐          ┌──────────────────┐
│   Humans    │          │  Agents / LLMs   │
└──────┬──────┘          └────────┬─────────┘
       │                          │
       ▼                          ▼
  README.md                   AGENTS.md
  docs/HUMAN.md               (protocol + tests
  docs/README.md               only here)
```

> **Agents:** start at [`AGENTS.md`](AGENTS.md). Do not invent features from `plan.md`.  
> **WebSocket message catalog** lives only in AGENTS — never mirrored into this README.

---

## Credits

- Inspired by **Dragon Quest I / Dragon Warrior** (NES-era combat math; not a ROM dump)
- Related library: [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat)
- Tile/hero placeholders: [Kenney.nl](https://kenney.nl) (CC0)
- Fan project — **not** Square Enix
