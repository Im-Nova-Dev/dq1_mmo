# DQ1 MMO — Human guide

This guide is for **people**: players, operators, and human contributors.

- **Install & feature overview** → [../README.md](../README.md)  
- **Coding agents / LLMs** → [../AGENTS.md](../AGENTS.md) (protocol, tests, code map)  
- **Docs index** → [README.md](README.md)

---

## What is this?

A small **multiplayer Dragon Quest I–style** game:

- Create an account and a hero.
- Walk a shared grid world (town, fields, dungeon).
- Fight with **server-side** DQ1 combat (attack, magic, flee).
- See other players nearby, use **global chat**, equip gear, and shop in town.

MVP limits: one map, no parties/PvP/trade, procedural art (colored tiles + DQ-style windows — not a full sprite pack).

**Current version:** 0.5.1

---

## Look & feel

The client aims for a classic Dragon Quest window style:

- Gold double-border panels and starfield title menus  
- HP/MP bars, combat command list, battle log  
- Overworld HUD, minimap, chat panel, nearby adventurers  
- Default window **1024×720** (resizable)

---

## Playing

### First session

1. Start the server ([README quick start](../README.md#quick-start)).
2. Run `love client`.
3. Register with email + password, then create a character.
4. On the hero screen: select a hero and **Enter World**, or **double-click** a hero card.
5. You spawn in **town** (safe — no random fights).

### World zones

| Zone | Look | Encounters |
|:-----|:-----|:-----------|
| **Town** | Warm brown tiles | None · shop works here |
| **Field** | Green | Common monsters |
| **Water** | Blue | Not walkable |
| **Dungeon** | Dark purple | Harder table, higher encounter rate |

### Combat

- Stepping in field/dungeon may start a fight.
- Choose **Attack**, **Flee**, or a **Spell** (spells unlock by level) with ↑↓ + Enter (or **A** / **F**).
- Victory: XP, gold, maybe a level-up toast.
- Defeat: wake in town, **half gold**, reduced HP (XP kept).
- Disconnect mid-fight: about **60 seconds** to reconnect and resume.

### Multiplayer social

- Nearby heroes on the map and in the **player list** (**P** / Tab).
- Players in combat show a **⚔** marker (and a combat ring).
- **T** opens global chat (all online players). Keep messages short; spam is rate-limited.
- **C** toggles the chat panel.

### Economy

- Start with some gold (default 300).
- In town, **I** → inventory; **Tab** opens the shop when available.
- **Enter** equip/buy · **S** sell · **U** unequip · **Esc** back.

---

## Controls (summary)

| Context | Keys |
|:--------|:-----|
| Overworld | WASD move · T chat · I inv · P list · B debug fight · Esc quit |
| Combat | ↑↓ menu · Enter · A attack · F flee |
| Inventory | ↑↓ · Enter · Tab shop · S sell · U unequip · Esc |
| Login / heroes | Tab fields · Enter · N new hero · Esc logout |

Full table: [README controls](../README.md#controls).

---

## Running a server (operators)

### Local development

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Optional: copy `.env.example` → `.env` and set `SECRET_KEY`.

### Production checklist

- `ENV=production` and a strong unique `SECRET_KEY`
- `ALLOW_DEBUG=0` (no forced encounters)
- Durable `DATABASE_URL` + backups of the SQLite file
- Explicit `CORS_ORIGINS`
- Google login only if OAuth env vars are set

### Health

`GET /health` → status, **version**, online players, active combats.

---

## Architecture (plain language)

```
┌─────────────┐     WebSocket JSON      ┌──────────────────┐
│ Love2D game │ ◄─────────────────────► │ Python game      │
│ (UI + input)│     REST for login      │ server (truth)   │
│             │                         │ + SQLite         │
└─────────────┘                         └──────────────────┘
```

- The **server** decides position, encounters, and damage.
- The **client** draws menus/map, predicts movement, and shows other players.
- Catalogs (enemies, spells, gear) live mainly in `shared/dq1_data.json`.

You only need Python if you host or develop the server.

---

## Testing multiplayer on one PC

- **Bots:** `./tools/mp_sim.sh`
- **Two windows:** `./tools/mp_love.sh 2` (two accounts)

Developer tests:

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
```

---

## Contributing (humans)

1. Prefer small, testable changes.
2. Run the test suite before proposing a change.
3. Keep the doc split clean:
   - **Players/ops** → this file + README  
   - **Agents** → [AGENTS.md](../AGENTS.md) only for protocol/tests/hot paths  

### Known MVP limits

- `client/assets/` is empty (procedural tiles/UI only).
- One small map; no quests, guilds, or trading.
- Big-number grind is only partially prepared (gold as strings).

---

## See also

- [Documentation index](README.md)
- [README (GitHub)](../README.md)
- [Agent / LLM contract](../AGENTS.md)
- Historical plan: [../plan.md](../plan.md) (not always current)
