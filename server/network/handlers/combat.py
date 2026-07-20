"""Combat actions (attack / flee / battle spell) — extracted.

Multiplayer reliability: turn gate (awaiting_hero only), field-only spells
blocked mid-fight, battle end publish_status + nearby outcome announce,
defeat respawn via publish_move (AOI), successful act mark_active (AFK clear),
combat_end / combat_update include online/nearby census for room orientation.
Field cast when not fighting stays in field_magic (this module returns None
for cast types outside combat so field path can own them if ordered first).
"""

from __future__ import annotations

from typing import Any

from game.combat_engine import combat_engine
from game.data_loader import get_spell
from game.world_manager import SPAWN_X, SPAWN_Y, zone_at
from network.handlers._common import (
    _announce_combat_outcome,
    _combat_update,
    _persist_battle_end,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

ATTACK_TYPES = frozenset({ClientMessageType.ATTACK, "attack"})
FLEE_TYPES = frozenset({ClientMessageType.FLEE, "flee"})
SPELL_TYPES = frozenset(
    {
        ClientMessageType.USE_SPELL,
        "use_spell",
        "cast",
        "cast_spell",
    }
)
COMBAT_ACTION_TYPES = frozenset({"combat_action"})
ALL_TYPES = ATTACK_TYPES | FLEE_TYPES | SPELL_TYPES | COMBAT_ACTION_TYPES


def _census(character_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    payload["online"] = len(manager.online_ids())
    payload["nearby_count"] = len(manager.ids_nearby(character_id))
    meta = manager.get_meta(character_id)
    if meta is not None:
        try:
            z = zone_at(int(meta["x"]), int(meta["y"]))
            if z in ("town", "field", "dungeon"):
                payload["zone"] = z
        except Exception:
            pass
    return payload


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch combat actions. Returns None if not a combat message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    # Cast / use_spell outside combat: field_magic owns them (must run first)
    if msg_type in SPELL_TYPES and not combat_engine.is_in_combat(
        character_id if character_id is not None else -1
    ):
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    battle = combat_engine.get(character_id)
    if battle is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="not in combat"))
        return character_id, user_id, outbound, None

    # Field-only spells must not be mis-routed as battle actions mid-fight
    if msg_type in SPELL_TYPES:
        sid = str(data.get("spell") or data.get("id") or "")
        sp = get_spell(sid) if sid else None
        if sp and sp.get("field") and not sp.get("battle"):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None

    if msg_type in ATTACK_TYPES or (
        msg_type in COMBAT_ACTION_TYPES and data.get("action") == "attack"
    ):
        action = {"type": "attack"}
    elif msg_type in FLEE_TYPES or (
        msg_type in COMBAT_ACTION_TYPES and data.get("action") == "flee"
    ):
        action = {"type": "flee"}
    else:
        spell = data.get("spell") or data.get("id")
        if msg_type in COMBAT_ACTION_TYPES:
            if data.get("action") == "spell":
                action = {"type": "spell", "id": spell}
            else:
                action = {"type": data.get("action"), "id": spell}
        else:
            action = {"type": "spell", "id": spell}

    # Only accept actions while awaiting hero input (blocks spam mid-resolve)
    if battle.phase != "awaiting_hero" or battle.outcome != "ongoing":
        outbound.append(msg(ServerMessageType.ERROR, reason="wait for your turn"))
        outbound.append(_census(character_id, _combat_update(battle, [])))
        return character_id, user_id, outbound, None

    result = battle.act(action)
    if not result["ok"]:
        outbound.append(
            msg(ServerMessageType.ERROR, reason=result.get("error") or "bad action")
        )
        outbound.append(_census(character_id, _combat_update(battle, [])))
        return character_id, user_id, outbound, None

    # Successful combat input is multiplayer activity — clear AFK for peers
    was_afk = manager.mark_active(character_id)
    if was_afk:
        await manager.publish_status(character_id, pulse_online=True)

    events = result["events"]
    outbound.append(_census(character_id, _combat_update(battle, events)))

    for e in events:
        if e.get("kind") == "level_up":
            outbound.append(
                msg(
                    ServerMessageType.LEVEL_UP,
                    new_level=e.get("level"),
                    new_stats=e.get("stats"),
                )
            )
            if e.get("level") is not None:
                await manager.publish_level(character_id, int(e["level"]))

    if battle.outcome != "ongoing":
        char = await _persist_battle_end(character_id, battle)
        combat_engine.end(character_id)
        manager.set_in_combat(character_id, False)
        if char.get("level"):
            manager.set_level(character_id, int(char["level"]))
        await manager.publish_status(character_id, pulse_online=True)
        end_payload: dict[str, Any] = {
            "result": battle.outcome,
            "xp": (battle.rewards or {}).get("xp", 0),
            "gold": (battle.rewards or {}).get("gold", 0),
            "character": char,
            "events": events,
        }
        if battle.outcome == "defeat":
            end_payload["gold_lost"] = int(char.pop("gold_lost", 0) or 0)
            end_payload["respawn"] = {"x": SPAWN_X, "y": SPAWN_Y}
        outbound.append(
            _census(character_id, msg(ServerMessageType.COMBAT_END, **end_payload))
        )
        # Multiplayer: nearby system note for victory / flee / defeat
        await _announce_combat_outcome(character_id, str(battle.outcome))
        if battle.outcome == "defeat":
            # Respawn in town with AOI refresh
            aoi_msgs = await manager.publish_move(
                character_id, SPAWN_X, SPAWN_Y, seq=None
            )
            outbound.extend(aoi_msgs)
            try:
                rzone = zone_at(SPAWN_X, SPAWN_Y)
            except Exception:
                rzone = "town"
            outbound.append(
                _census(
                    character_id,
                    msg(
                        ServerMessageType.MOVE_OK,
                        ok=True,
                        x=SPAWN_X,
                        y=SPAWN_Y,
                        seq=None,
                        reason="respawn",
                        zone=rzone,
                    ),
                )
            )
    return character_id, user_id, outbound, None
