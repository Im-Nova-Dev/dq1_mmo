import math
import re
from typing import Any

from auth.jwt_handler import decode_access_token
from config import ALLOW_DEBUG, COMBAT_GRACE_SECONDS
from database.db import db_write, get_db
from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at, field_spells_at, get_enemy
from game.enemy_spawner import roll_encounter
from game.item_manager import equipment_bonuses
from game.player_manager import apply_character_patch, get_character
from game.rng import Rng
from game.serialize import character_dict
from game.world_manager import (
    SPAWN_X,
    SPAWN_Y,
    is_adjacent_step,
    is_walkable,
    map_payload,
    zone_at,
)
from network.handlers import afk as afk_handlers
from network.handlers import askwhere as askwhere_handlers
from network.handlers import find as find_handlers
from network.handlers import hud_info as hud_info_handlers
from network.handlers import chat as chat_handlers
from network.handlers import emote as emote_handlers
from network.handlers import invite as invite_handlers
from network.handlers import invite_cancel as invite_cancel_handlers
from network.handlers import invite_reply as invite_reply_handlers
from network.handlers import inn as inn_handlers
from network.handlers import inventory as inventory_handlers
from network.handlers import shop as shop_handlers
from network.handlers import whisper as whisper_handlers
from network.handlers import look as look_handlers
from network.handlers import meta_peeks as meta_peek_handlers
from network.handlers import mute as mute_handlers
from network.handlers import poke as poke_handlers
from network.handlers import presence_peeks
from network.handlers import roll as roll_handlers
from network.handlers import safety as safety_handlers
from network.handlers import self_peeks as self_peek_handlers
from network.handlers import session as session_handlers
from network.handlers import share as share_handlers
from network.handlers import social_peeks
from network.handlers import status as status_handlers
from network.handlers import thank as thank_handlers
from network.handlers import use_item as use_item_handlers
from network.handlers import field_magic as field_magic_handlers
from network.handlers import combat as combat_handlers
from network.handlers._common import (  # noqa: F401 — re-export for tests
    _afk_snap,
    _announce_combat_outcome,
    _combat_update,
    _format_uptime,
    _inventory_msg,
    _parse_positive_qty,
    _persist_battle_end,
    _resolve_item_arg,
    _resolve_social_peer,
    _social_alias,
    best_effort_send,
    peer_status_suffix,
    private_social_delivery,
    sanitize_chat,
    social_peer_card,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import CHAT_MAX_LEN, manager


async def handle_disconnect(character_id: int) -> None:
    """Persist position; keep combat alive for a grace period so reconnect can resume."""
    meta = manager.get_meta(character_id)
    patch: dict = {}
    if meta is not None:
        patch["world_x"] = meta["x"]
        patch["world_y"] = meta["y"]
        manager.mark_clean(character_id)

    battle = combat_engine.get(character_id)
    if battle is not None and battle.outcome == "ongoing":
        # Soft-save HP/MP but do not end the fight yet
        patch["current_hp"] = max(1, int(battle.hero["hp"]))
        patch["current_mp"] = max(0, int(battle.hero["mp"]))
        combat_engine.mark_disconnected(character_id, COMBAT_GRACE_SECONDS)
    elif battle is not None:
        combat_engine.end(character_id)

    if patch:
        await apply_character_patch(character_id, patch)


async def expire_combat_grace(character_id: int) -> None:
    """Called when reconnect grace expires — end battle without rewards."""
    battle = combat_engine.get(character_id)
    if battle is None:
        combat_engine.clear_disconnect(character_id)
        return
    patch = {
        "current_hp": max(1, int(battle.hero["hp"])),
        "current_mp": max(0, int(battle.hero["mp"])),
    }
    await apply_character_patch(character_id, patch)
    combat_engine.end(character_id)
    manager.set_in_combat(character_id, False)
    await manager.publish_status(character_id, pulse_online=True)


async def handle_message(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
) -> tuple[int | None, int | None, list[dict], dict | None]:
    msg_type = data.get("type")
    outbound: list[dict] = []
    connect_meta: dict | None = None

    if msg_type in session_handlers.PING_TYPES or msg_type == ClientMessageType.PING:
        return await session_handlers.handle_ping(
            character_id, user_id, data, outbound
        )

    if msg_type in session_handlers.SYNC_TYPES:
        return await session_handlers.handle_sync(
            character_id, user_id, data, outbound
        )

    social_peek = await social_peeks.handle(
        character_id, user_id, data, outbound
    )
    if social_peek is not None:
        return social_peek

    look_peek = await look_handlers.handle(
        character_id, user_id, data, outbound
    )
    if look_peek is not None:
        return look_peek

    status_peek = await status_handlers.handle(
        character_id, user_id, data, outbound
    )
    if status_peek is not None:
        return status_peek

    self_peek = await self_peek_handlers.handle(
        character_id, user_id, data, outbound
    )
    if self_peek is not None:
        return self_peek

    meta_peek = await meta_peek_handlers.handle(
        character_id, user_id, data, outbound
    )
    if meta_peek is not None:
        return meta_peek

    presence_peek = await presence_peeks.handle(
        character_id, user_id, data, outbound
    )
    if presence_peek is not None:
        return presence_peek

    mute_peek = await mute_handlers.handle(
        character_id, user_id, data, outbound
    )
    if mute_peek is not None:
        return mute_peek

    hud_peek = await hud_info_handlers.handle(
        character_id, user_id, data, outbound
    )
    if hud_peek is not None:
        return hud_peek

    afk_peek = await afk_handlers.handle(
        character_id, user_id, data, outbound
    )
    if afk_peek is not None:
        return afk_peek

    safety_peek = await safety_handlers.handle(
        character_id, user_id, data, outbound
    )
    if safety_peek is not None:
        return safety_peek

    find_peek = await find_handlers.handle(
        character_id, user_id, data, outbound
    )
    if find_peek is not None:
        return find_peek

    roll_peek = await roll_handlers.handle(
        character_id, user_id, data, outbound
    )
    if roll_peek is not None:
        return roll_peek

    poke_peek = await poke_handlers.handle(
        character_id, user_id, data, outbound
    )
    if poke_peek is not None:
        return poke_peek

    thank_peek = await thank_handlers.handle(
        character_id, user_id, data, outbound
    )
    if thank_peek is not None:
        return thank_peek

    askwhere_peek = await askwhere_handlers.handle(
        character_id, user_id, data, outbound
    )
    if askwhere_peek is not None:
        return askwhere_peek

    share_peek = await share_handlers.handle(
        character_id, user_id, data, outbound
    )
    if share_peek is not None:
        return share_peek

    cancel_peek = await invite_cancel_handlers.handle(
        character_id, user_id, data, outbound
    )
    if cancel_peek is not None:
        return cancel_peek

    invite_peek = await invite_handlers.handle(
        character_id, user_id, data, outbound
    )
    if invite_peek is not None:
        return invite_peek

    reply_peek = await invite_reply_handlers.handle(
        character_id, user_id, data, outbound
    )
    if reply_peek is not None:
        return reply_peek

    emote_peek = await emote_handlers.handle(
        character_id, user_id, data, outbound
    )
    if emote_peek is not None:
        return emote_peek

    whisper_peek = await whisper_handlers.handle(
        character_id, user_id, data, outbound
    )
    if whisper_peek is not None:
        return whisper_peek

    chat_peek = await chat_handlers.handle(
        character_id, user_id, data, outbound
    )
    if chat_peek is not None:
        return chat_peek

    shop_peek = await shop_handlers.handle(
        character_id, user_id, data, outbound
    )
    if shop_peek is not None:
        return shop_peek

    inv_peek = await inventory_handlers.handle(
        character_id, user_id, data, outbound
    )
    if inv_peek is not None:
        return inv_peek

    inn_peek = await inn_handlers.handle(
        character_id, user_id, data, outbound
    )
    if inn_peek is not None:
        return inn_peek

    use_peek = await use_item_handlers.handle(
        character_id, user_id, data, outbound
    )
    if use_peek is not None:
        return use_peek

    field_peek = await field_magic_handlers.handle(
        character_id, user_id, data, outbound
    )
    if field_peek is not None:
        return field_peek

    combat_peek = await combat_handlers.handle(
        character_id, user_id, data, outbound
    )
    if combat_peek is not None:
        return combat_peek

    # peeks + social + shop/inventory/inn/use_item/field_magic/combat via handlers

    # fighting via presence_peeks · quit/stuck via safety

    # version / played / time via meta_peeks · ignore/unignore/ignores via mute

    # find handled via network.handlers.find

    if msg_type == ClientMessageType.AUTH:
        token = data.get("token")
        char_id = data.get("character_id")
        if not token or not char_id:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="token and character_id required"))
            return character_id, user_id, outbound, None

        payload = decode_access_token(token)
        if payload is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="invalid token"))
            return character_id, user_id, outbound, None

        db = await get_db()
        async with db.execute(
            "SELECT * FROM characters WHERE id = ? AND user_id = ?",
            (int(char_id), payload["user_id"]),
        ) as c:
            row = await c.fetchone()
        if row is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="character not found"))
            return character_id, user_id, outbound, None

        character = character_dict(row)
        x = int(character["world_x"])
        y = int(character["world_y"])
        if not is_walkable(x, y):
            x, y = SPAWN_X, SPAWN_Y
            async with db_write() as wdb:
                await wdb.execute(
                    "UPDATE characters SET world_x = ?, world_y = ? WHERE id = ?",
                    (x, y, character["id"]),
                )
                await wdb.commit()
            character["world_x"] = x
            character["world_y"] = y

        character["known_spells"] = battle_spells_at(int(character["level"]))
        character["field_spells"] = field_spells_at(int(character["level"]))
        character["bonuses"] = equipment_bonuses(character)
        from game.progression import xp_to_next_level

        character["xp_progress"] = xp_to_next_level(
            int(character.get("experience") or 0),
            int(character.get("level") or 1),
        )

        resume_battle = combat_engine.get(character["id"])
        if resume_battle is not None and resume_battle.outcome == "ongoing":
            combat_engine.clear_disconnect(character["id"])
            character["current_hp"] = resume_battle.hero["hp"]
            character["current_mp"] = resume_battle.hero["mp"]
            character["in_combat"] = True
        else:
            character["in_combat"] = False
            if resume_battle is not None:
                combat_engine.end(character["id"])

        connect_meta = {
            "character_id": character["id"],
            "name": character["name"],
            "x": character["world_x"],
            "y": character["world_y"],
            "map_id": character["map_id"],
            "level": character["level"],
            "in_combat": bool(character.get("in_combat")),
        }

        outbound.append(
            msg(
                ServerMessageType.AUTH_OK,
                player_id=character["id"],
                character=character,
                map=map_payload(),
                in_combat=bool(character.get("in_combat")),
            )
        )
        outbound.append(msg(ServerMessageType.WORLD_STATE, players=[], enemies=[], map=map_payload()))

        if resume_battle is not None and resume_battle.outcome == "ongoing":
            snap = resume_battle.snapshot()
            outbound.append(
                msg(
                    ServerMessageType.COMBAT_RESUME,
                    enemy=snap["enemy"],
                    hero=snap["hero"],
                    legal_actions=snap["legal_actions"],
                    turn=snap["turn"],
                    phase=snap["phase"],
                    events=[{"kind": "message", "message": "Battle resumed!"}],
                )
            )
            outbound.append(_combat_update(resume_battle, []))

        return character["id"], payload["user_id"], outbound, connect_meta

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    # Drop ghost sessions if the hero row was deleted while still connected
    _needs_char = msg_type in (
        ClientMessageType.MOVE,
        ClientMessageType.ATTACK,
        ClientMessageType.FLEE,
        ClientMessageType.USE_SPELL,
        ClientMessageType.USE_ITEM,
        ClientMessageType.EQUIP,
        ClientMessageType.UNEQUIP,
        ClientMessageType.BUY,
        ClientMessageType.SELL,
        ClientMessageType.REST,
        ClientMessageType.SHOP,
        ClientMessageType.INVENTORY,
        "use_spell",
        "cast",
        "cast_spell",
        "use_item",
        "rest",
        "inn",
        "debug_encounter",
        "combat_action",
    )
    if _needs_char:
        _alive = await get_character(character_id)
        if _alive is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            try:
                await manager.disconnect(character_id)
            except Exception:
                pass
            return character_id, user_id, outbound, None

    # field magic + combat actions via handlers

    # --- Movement (server-authoritative, ack'd, rate-limited, DB-deferred) ---
    if msg_type == ClientMessageType.MOVE:
        raw_seq = data.get("seq")
        seq: int | None
        # bool is a subclass of int — reject before numeric coercion
        if isinstance(raw_seq, bool):
            seq = None
            _bad_seq = True
        elif isinstance(raw_seq, int):
            seq = raw_seq
            _bad_seq = False
        elif isinstance(raw_seq, float):
            seq = int(raw_seq)
            _bad_seq = False
        elif isinstance(raw_seq, str) and raw_seq.strip().lstrip("-").isdigit():
            # Loose clients may send "2" — coerce digit strings
            seq = int(raw_seq.strip())
            _bad_seq = False
        elif raw_seq is None:
            seq = None
            _bad_seq = False  # seq optional
        else:
            seq = None
            _bad_seq = True
        # Reject non-positive seq (client always starts at 1; negatives used to
        # trip the duplicate path because last_move_seq defaults to 0).
        if _bad_seq or (seq is not None and seq < 1):
            meta = manager.get_meta(character_id)
            mx = int(meta["x"]) if meta else 0
            my = int(meta["y"]) if meta else 0
            outbound.append(
                msg(
                    ServerMessageType.MOVE_OK,
                    ok=False,
                    x=mx,
                    y=my,
                    seq=seq if isinstance(seq, int) and not isinstance(raw_seq, bool) else None,
                    reason="invalid seq",
                )
            )
            return character_id, user_id, outbound, None

        def _reject(reason: str, mx: int, my: int) -> None:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason=reason,
                    x=mx,
                    y=my,
                    seq=seq,
                )
            )
            # Always ack so client can reconcile
            outbound.append(msg(ServerMessageType.MOVE_OK, ok=False, x=mx, y=my, seq=seq, reason=reason))

        if combat_engine.is_in_combat(character_id):
            meta = manager.get_meta(character_id)
            mx = int(meta["x"]) if meta else 0
            my = int(meta["y"]) if meta else 0
            _reject("in combat", mx, my)
            return character_id, user_id, outbound, None

        x = data.get("x")
        y = data.get("y")

        def _finite_num(v: Any) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))

        if not _finite_num(x) or not _finite_num(y):
            meta = manager.get_meta(character_id)
            try:
                mx = int(meta["x"]) if meta and math.isfinite(float(meta["x"])) else 0
                my = int(meta["y"]) if meta and math.isfinite(float(meta["y"])) else 0
            except (TypeError, ValueError, OverflowError):
                mx, my = 0, 0
            _reject("invalid move", mx, my)
            return character_id, user_id, outbound, None

        # Reject non-integer coords (3.7 must not silently become 3 — desyncs clients)
        try:
            fx_n, fy_n = float(x), float(y)
            if not fx_n.is_integer() or not fy_n.is_integer():
                meta = manager.get_meta(character_id)
                mx = int(meta["x"]) if meta else 0
                my = int(meta["y"]) if meta else 0
                _reject("invalid move", mx, my)
                return character_id, user_id, outbound, None
            tx, ty = int(fx_n), int(fy_n)
        except (TypeError, ValueError, OverflowError):
            meta = manager.get_meta(character_id)
            mx = int(meta["x"]) if meta else 0
            my = int(meta["y"]) if meta else 0
            _reject("invalid move", mx, my)
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if meta is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="not connected"))
            return character_id, user_id, outbound, None

        # Defend against corrupted meta (e.g. prior non-finite inject)
        try:
            fx, fy = int(meta["x"]), int(meta["y"])
            if not math.isfinite(float(meta["x"])) or not math.isfinite(float(meta["y"])):
                raise ValueError("non-finite meta pos")
        except (TypeError, ValueError, OverflowError):
            fx, fy = SPAWN_X, SPAWN_Y
            meta["x"], meta["y"] = float(fx), float(fy)

        # Duplicate / old seq: ignore but confirm current pos (idempotent)
        last_seq = int(meta.get("last_move_seq") or 0)
        if seq is not None and seq <= last_seq:
            outbound.append(
                msg(ServerMessageType.MOVE_OK, ok=True, x=fx, y=fy, seq=seq, duplicate=True)
            )
            return character_id, user_id, outbound, None

        # Validate geometry before burning the move rate budget — rejected
        # wall/non-adjacent steps must not lock the player out of the next step.
        if not is_adjacent_step(fx, fy, tx, ty):
            _reject("invalid step", fx, fy)
            return character_id, user_id, outbound, None

        if not is_walkable(tx, ty):
            _reject("blocked", fx, fy)
            return character_id, user_id, outbound, None

        # Capture AFK before allow_move clears it so peers get an idle-clear update
        was_afk = bool(meta.get("afk"))
        allowed, retry = manager.allow_move(character_id)
        if not allowed:
            outbound.append(
                msg(
                    ServerMessageType.MOVE_OK,
                    ok=False,
                    x=fx,
                    y=fy,
                    seq=seq,
                    reason="rate_limit",
                    retry_after=round(retry, 3),
                )
            )
            return character_id, user_id, outbound, None

        # Apply position + AOI (enter/leave range notifications)
        aoi_msgs = await manager.publish_move(character_id, tx, ty, seq=seq)
        new_zone = zone_at(tx, ty)
        old_zone = zone_at(fx, fy)
        outbound.append(
            msg(
                ServerMessageType.MOVE_OK,
                ok=True,
                x=tx,
                y=ty,
                seq=seq,
                zone=new_zone,
            )
        )
        outbound.extend(aoi_msgs)
        # Multiplayer: walking clears manual AFK — notify AOI + roster
        if was_afk:
            await manager.publish_status(character_id, pulse_online=True)

        # Multiplayer: soft nearby system note when crossing zone types
        # (town ↔ field ↔ dungeon). Quiet for same-zone steps.
        if (
            old_zone != new_zone
            and old_zone in ("town", "field", "dungeon")
            and new_zone in ("town", "field", "dungeon")
        ):
            meta_now = manager.get_meta(character_id)
            hero = (meta_now or {}).get("name") or "Hero"
            await manager.broadcast_nearby(
                character_id,
                msg(
                    ServerMessageType.CHAT,
                    player_id=character_id,
                    name="System",
                    text=f"{hero} entered the {new_zone}.",
                    channel="system",
                    system=True,
                    zone=new_zone,
                ),
                include_self=True,
                respect_ignore=False,
            )

        # Fairy Water / REPEL: consume a step; while active, skip random fights
        if manager.consume_repel_step(character_id):
            return character_id, user_id, outbound, None

        # RADIANT: soft light in dungeons (lower encounter rate); tick each step
        lit = manager.radiant_remaining(character_id) > 0
        if lit:
            # Only consume steps while light is "used" (any zone) so duration is finite
            manager.consume_radiant_step(character_id)

        # Random encounter (radiant reduces dungeon rate)
        enemy_id = roll_encounter(tx, ty, Rng(), radiant=lit)
        if enemy_id:
            async with db_write() as db:
                await db.execute(
                    "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (tx, ty, character_id),
                )
                await db.commit()
            manager.mark_clean(character_id)

            char = await get_character(character_id)
            if char and not combat_engine.is_in_combat(character_id):
                char["known_spells"] = battle_spells_at(int(char["level"]))
                try:
                    battle = combat_engine.start(character_id, char, enemy_id)
                except RuntimeError:
                    # Concurrent start race — leave player out of a forced fight
                    return character_id, user_id, outbound, None
                manager.set_in_combat(character_id, True)
                await manager.publish_status(character_id, pulse_online=True)
                # Multiplayer: nearby notice that a hero engaged (not global spam)
                hero_nm = (manager.get_meta(character_id) or {}).get("name") or "Hero"
                await manager.broadcast_nearby(
                    character_id,
                    msg(
                        ServerMessageType.CHAT,
                        player_id=character_id,
                        name="System",
                        text=f"{hero_nm} is fighting!",
                        channel="system",
                        system=True,
                    ),
                    include_self=False,
                    respect_ignore=False,
                )
                start_events = battle._take_batch()
                outbound.append(
                    msg(
                        ServerMessageType.COMBAT_START,
                        enemy=battle.enemy_public(),
                        hero=battle.hero_public(),
                        legal_actions=battle.legal_actions(),
                        events=start_events,
                    )
                )
                outbound.append(_combat_update(battle, start_events))

        return character_id, user_id, outbound, None

    # whisper · chat · emotes · use_item · inventory · shop · inn via handlers

    # Debug/test: force encounter (ALLOW_DEBUG=1)
    if msg_type == "debug_encounter":
        if not ALLOW_DEBUG:
            outbound.append(msg(ServerMessageType.ERROR, reason="debug disabled"))
            return character_id, user_id, outbound, None
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="already in combat"))
            return character_id, user_id, outbound, None
        enemy_id = data.get("enemy") or "slime"
        if get_enemy(str(enemy_id)) is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="unknown enemy"))
            return character_id, user_id, outbound, None
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        char["known_spells"] = battle_spells_at(int(char["level"]))
        seed = data.get("seed")
        if seed is not None and not isinstance(seed, int):
            seed = None
        try:
            battle = combat_engine.start(character_id, char, str(enemy_id), seed=seed)
        except RuntimeError:
            outbound.append(msg(ServerMessageType.ERROR, reason="already in combat"))
            return character_id, user_id, outbound, None
        manager.set_in_combat(character_id, True)
        await manager.publish_status(character_id, pulse_online=True)
        hero_nm = (manager.get_meta(character_id) or {}).get("name") or "Hero"
        await manager.broadcast_nearby(
            character_id,
            msg(
                ServerMessageType.CHAT,
                player_id=character_id,
                name="System",
                text=f"{hero_nm} is fighting!",
                channel="system",
                system=True,
            ),
            include_self=False,
            respect_ignore=False,
        )
        start_events = battle._take_batch()
        outbound.append(
            msg(
                ServerMessageType.COMBAT_START,
                enemy=battle.enemy_public(),
                hero=battle.hero_public(),
                legal_actions=battle.legal_actions(),
                events=start_events,
            )
        )
        outbound.append(_combat_update(battle, start_events))
        return character_id, user_id, outbound, None

    outbound.append(msg(ServerMessageType.ERROR, reason=f"unknown or unsupported type: {msg_type}"))
    return character_id, user_id, outbound, None
