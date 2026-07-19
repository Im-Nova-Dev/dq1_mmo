# Documentation index

This project keeps **human** and **agent/LLM** documentation separate so each audience gets the right level of detail.

| Document | Audience | Purpose |
|:---------|:---------|:--------|
| [../README.md](../README.md) | Everyone (GitHub landing) | Install, controls, features, layout |
| [HUMAN.md](HUMAN.md) | Players, operators, human contributors | Gameplay, menus, hosting |
| [../AGENTS.md](../AGENTS.md) | Coding agents / LLMs | Protocol, hot paths, tests, constraints |
| [../plan.md](../plan.md) | Historical only | Original multi-phase plan — may be outdated |

**Last docs refresh:** v0.5.1 (UI polish, multiplayer chat/presence, test suites documented).

## Rules of thumb

1. **Players / operators** → `README.md` then `HUMAN.md`.
2. **Agents implementing features** → `AGENTS.md` first, then code, then update docs.
3. **Do not** put long WebSocket protocol matrices in the README — keep them in `AGENTS.md`.
4. **Do not** put “how do I play?” only in `AGENTS.md` — keep that in README / HUMAN.
5. **Do not** treat `plan.md` as the live backlog.

## Keeping docs current

When behavior changes that people or integrators see:

- [ ] `README.md` — version, features, controls, layout  
- [ ] `docs/HUMAN.md` — gameplay / ops  
- [ ] `AGENTS.md` — protocol, hot paths, tests (if agents need it)  
- [ ] `server/config.py` `VERSION` matches README  

When you only refactor internals with no behavior change: a short note in `AGENTS.md` hot paths is enough.
