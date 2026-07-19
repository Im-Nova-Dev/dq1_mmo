# DQ1 MMO — Human guide

For **people** (players, operators, human contributors).

| You want… | Go here |
|:----------|:--------|
| Install & overview | [../README.md](../README.md) |
| AI / protocol docs | [../AGENTS.md](../AGENTS.md) |
| Docs index | [README.md](README.md) |
| Swap sprites | [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) |

**Version:** 0.5.9 · synced 2026-07-19

---

## What is this?

Multiplayer **Dragon Quest I–style** game:

- Account + hero (gold + **3 herbs**)
- Shared town / field / dungeon
- Server-side combat (attack, magic, flee, herbs)
- Town **inn** and **field magic** (Heal, Return, …)
- Chat (global + nearby), emotes, live **online roster**
- Shop, gear, swappable PNG art

MVP: one map; no parties, PvP, trade, or quests.

---

## Playing

### First session

1. Start server · `love client`
2. Register · create hero · Enter World
3. Town is safe

### Zones

| Zone | Notes |
|:-----|:------|
| Town | Shop · **inn (R)** · no fights |
| Field | Random encounters |
| Water | Blocked |
| Dungeon | Harder fights · Outside spell exits |

### Combat

Attack / Flee / Spells / **Herb (H)**.  
Defeat → town, half gold. Disconnect mid-fight: ~60s to resume.

### Inn

**R** in town → full HP/MP for **max(4, level×4)** gold.

### Field magic

Learned by level (same as classic DQ1 progression).

| Key | Action |
|:----|:-------|
| **H** | Heal / Healmore on the field |
| **M** | Cycle Return, Repel, Outside, Radiant, … |

- **Return** → town  
- **Repel** → fewer random fights for a while  
- **Outside** → leave dungeon to the field  

### Items

| Item | Effect |
|:-----|:-------|
| Herb | Heal (world + battle) |
| Wings | Warp to town |
| Fairy Water | Temporary repel |

**Enter** uses consumables or equips gear. **Tab** in inventory = shop (town).

### Social

| Key | Effect |
|:----|:-------|
| **T** / **Y** | Global / nearby chat |
| **E** | Wave |
| **O** or **P** | Who’s online / nearby |
| **C** | Toggle chat |

HUD shows nearby + online counts. Online roster updates when people join/leave (names/levels only, not map positions). ⚔ = in combat.

---

## Controls

| Context | Keys |
|:--------|:-----|
| Overworld | WASD · T/Y chat · E wave · R inn · H/M magic · O who · I · Esc |
| Combat | ↑↓ · Enter · A / F / H |
| Inventory | Enter · R inn · S sell · U unequip · Tab shop |

---

## Hosting

```bash
cd server && source .venv/bin/activate && ./run.sh
```

Prod: strong `SECRET_KEY`, `ENV=production`, `ALLOW_DEBUG=0`, durable DB, tight CORS.  
Health: `GET /health`.

---

## Multiplayer on one PC

`./tools/mp_sim.sh` · `./tools/mp_love.sh 2`  
Tests: `python tests/run_tests.py` in `server/`.

---

## Docs: humans vs agents

- **You** → this file + README  
- **Coding agents** → [AGENTS.md](../AGENTS.md) for protocol/tests only  

Do not put long protocol tables in human docs.
