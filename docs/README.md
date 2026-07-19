# Documentation index

**Human** documentation and **agent / LLM** documentation are intentionally separate.

| Document | Audience | Purpose |
|:---------|:---------|:--------|
| [../README.md](../README.md) | Everyone (GitHub) | Install, features, controls — polished human entry |
| [HUMAN.md](HUMAN.md) | Players, operators | Gameplay, inn, magic, social, hosting |
| [../AGENTS.md](../AGENTS.md) | Coding agents / LLMs | Protocol matrices, hot paths, tests, reliability rules |
| [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) | Artists | PNG names & licenses |
| [../plan.md](../plan.md) | Historical only | Original roadmap — **not** live source of truth |

**Last docs refresh:** **v0.5.15** (2026-07-19)  
Look/examine · online pulse debounce · field-spell combat guard · **90** tests · multiplayer reliability.

---

## Audience rules

| Do | Don’t |
|:---|:------|
| Put install & controls in README / HUMAN | Dump full WS protocol tables into README |
| Put protocol, tests, agent constraints in `AGENTS.md` | Put “how to install Love2D for players” only in AGENTS |
| Treat `plan.md` as history | Treat `plan.md` as the current backlog |
| Bump `VERSION` in `server/config.py` with user-visible changes | Leave README / HUMAN version out of date |

### Quick map

```text
Humans  ──►  README.md  +  docs/HUMAN.md
Agents  ──►  AGENTS.md   (protocol + tests + hot paths)
Art     ──►  client/assets/ATTRIBUTION.md
```

---

## When the game changes

Checklist for contributors (human or agent):

- [ ] `server/config.py` → `VERSION`
- [ ] [README.md](../README.md) version badge / features / controls
- [ ] [HUMAN.md](HUMAN.md) gameplay if player-facing
- [ ] [AGENTS.md](../AGENTS.md) protocol / tests / reliability if agent-facing
- [ ] This index “last refresh” line
