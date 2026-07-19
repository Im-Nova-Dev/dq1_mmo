"""Adversarial / edge-case tests — try to break world, combat, items, chat."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.combat_engine import Battle, combat_engine
from game.data_loader import get_enemy, get_spell, load_data
from game.enemy_spawner import DUNGEON_WEIGHTS, FIELD_WEIGHTS, roll_encounter, weighted_pick
from game.formulas import breath_damage, hurt_damage, hurtmore_damage, roll_encounter_hp
from game.item_manager import equipment_bonuses, shop_catalog
from game.progression import apply_xp, gold_add, level_for_xp
from game.rng import Rng
from game.world_manager import (
    MAP_HEIGHT,
    MAP_WIDTH,
    SPAWN_X,
    SPAWN_Y,
    is_adjacent_step,
    is_walkable,
    map_payload,
    tile_at,
    zone_at,
)
from network.message_handler import sanitize_chat


def _hero(**kw):
    base = {
        "name": "Adv",
        "level": 1,
        "strength": 4,
        "agility": 4,
        "max_hp": 15,
        "max_mp": 0,
        "current_hp": 15,
        "current_mp": 0,
        "experience": 0,
        "gold": "0",
    }
    base.update(kw)
    return base


# --- World ---


def test_world_bounds_and_spawn():
    assert is_walkable(SPAWN_X, SPAWN_Y)
    assert zone_at(SPAWN_X, SPAWN_Y) == "town"
    assert not is_walkable(-1, 0)
    assert not is_walkable(0, -1)
    assert not is_walkable(MAP_WIDTH, 0)
    assert not is_walkable(0, MAP_HEIGHT)
    assert tile_at(-5, -5) == 1  # wall OOB
    assert not is_adjacent_step(2, 2, 3, 3)  # no diagonals
    assert is_adjacent_step(2, 2, 3, 2)
    payload = map_payload()
    assert payload["width"] == MAP_WIDTH
    assert len(payload["tiles"]) == MAP_HEIGHT


def test_zones_match_tiles():
    # sample known cells from MVP_MAP
    assert zone_at(2, 2) == "town"
    assert zone_at(7, 1) == "field"
    assert zone_at(7, 7) == "blocked"  # water
    assert zone_at(17, 1) == "dungeon"


def test_encounter_tables_all_exist():
    for eid in FIELD_WEIGHTS:
        assert get_enemy(eid), f"missing field enemy {eid}"
    for eid in DUNGEON_WEIGHTS:
        assert get_enemy(eid), f"missing dungeon enemy {eid}"
    # town never encounters
    for _ in range(50):
        assert roll_encounter(SPAWN_X, SPAWN_Y, Rng()) is None


def test_weighted_pick_deterministic():
    a = weighted_pick(Rng(99), FIELD_WEIGHTS)
    b = weighted_pick(Rng(99), FIELD_WEIGHTS)
    assert a == b
    assert a in FIELD_WEIGHTS


# --- Combat edges ---


def test_unknown_enemy_raises():
    try:
        Battle(_hero(), "definitely_not_real")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unknown" in str(e).lower()


def test_act_after_battle_ended_rejected():
    b = Battle(_hero(strength=99, agility=99, max_hp=200, current_hp=200), "slime", seed=0)
    for _ in range(40):
        if b.outcome != "ongoing":
            break
        assert b.act({"type": "attack"})["ok"]
    assert b.outcome != "ongoing"
    r = b.act({"type": "attack"})
    assert r["ok"] is False
    assert r["error"]


def test_illegal_spell_and_empty_action():
    b = Battle(_hero(), "slime", seed=1)
    assert b.act({"type": "spell", "id": "hurt"})["ok"] is False
    assert b.act({"type": "dance"})["ok"] is False
    assert b.act({})["ok"] is False


def test_heal_at_full_hp_still_legal_and_spends_mp():
    b = Battle(
        _hero(level=4, max_mp=20, current_mp=20, max_hp=40, current_hp=40, known_spells=["heal"]),
        "slime",
        seed=5,
    )
    before_mp = b.hero["mp"]
    r = b.act({"type": "spell", "id": "heal"})
    assert r["ok"] is True
    assert b.hero["mp"] < before_mp
    # Heal at full HP yields 0 actual; enemy may still act afterward
    heals = [e for e in r["events"] if e.get("kind") == "heal"]
    assert heals and heals[0].get("amount") == 0


def test_level_up_syncs_battle_hp_mp():
    """Regression: apply_xp must heal live battle hp/mp keys, not only current_*."""
    b = Battle(
        _hero(experience=6, current_hp=10, max_hp=15, strength=20, agility=20),
        "slime",
        seed=42,
    )
    # chip self so hp < max if enemy hits; then win for +1 XP → level 2
    for _ in range(40):
        if b.outcome != "ongoing":
            break
        b.act({"type": "attack"})
    assert b.outcome == "victory"
    assert b.hero["level"] == 2
    # full heal on level-up should apply to combat pool
    assert b.hero["hp"] == b.hero["max_hp"], (
        f"hp={b.hero['hp']} max={b.hero['max_hp']} current_hp={b.hero.get('current_hp')}"
    )
    assert b.hero.get("current_hp") == b.hero["max_hp"]
    patch = b.character_patch()
    assert patch["current_hp"] == patch["max_hp"]
    assert patch["level"] == 2


def test_flee_always_succeeds_if_enemy_asleep():
    b = Battle(
        _hero(level=5, max_mp=30, current_mp=30, known_spells=["sleep"], agility=5),
        "slime",
        seed=3,
    )
    slept = False
    for _ in range(15):
        if b.outcome != "ongoing":
            break
        if b.enemy["status"]["sleep"]:
            r = b.act({"type": "flee"})
            assert r["ok"]
            assert b.outcome == "fled"
            slept = True
            break
        if any(a.get("id") == "sleep" for a in b.legal_actions()):
            b.act({"type": "spell", "id": "sleep"})
        else:
            b.act({"type": "attack"})
    assert slept, "could not apply sleep to verify flee"


def test_defeat_patch_keeps_gold_for_handler():
    b = Battle(
        _hero(strength=1, agility=1, max_hp=1, current_hp=1, gold="100"),
        "dragonlord" if get_enemy("dragonlord") else "armored_knight",
        seed=1,
    )
    for _ in range(30):
        if b.outcome != "ongoing":
            break
        b.act({"type": "attack"})
    assert b.outcome == "defeat"
    patch = b.character_patch()
    assert patch["current_hp"] >= 1
    assert patch["gold"] == "100"  # half-gold applied in message_handler, not engine


def test_all_enemies_can_start_battle():
    data = load_data()
    for eid in list(data["enemies"].keys())[:15]:  # sample first 15 + ensure metal
        b = Battle(_hero(strength=50, agility=50, max_hp=200, current_hp=200), eid, seed=1)
        assert b.outcome == "ongoing"
        assert b.enemy["hp"] >= 1
    if get_enemy("metal_slime"):
        b = Battle(_hero(max_hp=50, current_hp=50), "metal_slime", seed=2)
        assert b.enemy["hp"] <= b.enemy["max_hp"]


def test_enemy_breath_and_magic_patterns_run():
    # Pick an enemy with breath if available
    breath_id = None
    for eid, e in load_data()["enemies"].items():
        steps = (e.get("pattern") or {}).get("steps") or []
        if any(s.get("action") in ("breath", "breath_strong") for s in steps):
            breath_id = eid
            break
    if not breath_id:
        return  # skip if catalog lacks breath
    b = Battle(
        _hero(strength=1, agility=1, max_hp=500, current_hp=500),
        breath_id,
        seed=11,
    )
    for _ in range(5):
        if b.outcome != "ongoing":
            break
        b.act({"type": "attack"})
    # survived or died — must not crash
    assert b.outcome in ("ongoing", "defeat", "victory")


# --- Formulas / progression ---


def test_hurt_bands_adversarial():
    for seed in range(20):
        d = hurt_damage(Rng(seed))
        assert 5 <= d <= 12
        d2 = hurtmore_damage(Rng(seed))
        assert 58 <= d2 <= 65
        b = breath_damage(Rng(seed), False)
        assert 16 <= b <= 23
        b2 = breath_damage(Rng(seed), True)
        assert 65 <= b2 <= 72


def test_encounter_hp_band():
    for seed in range(30):
        hp = roll_encounter_hp(100, Rng(seed))
        assert 75 <= hp <= 100


def test_level_for_xp_caps():
    assert level_for_xp(0) == 1
    assert level_for_xp(10**9) <= 30
    hero = _hero(experience=0, level=1)
    apply_xp(hero, 0)
    assert hero["level"] == 1


def test_gold_add_string():
    h = {"gold": "10"}
    gold_add(h, 5)
    assert h["gold"] == "15"
    gold_add(h, 0)
    assert h["gold"] == "15"
    gold_add(h, -100)
    assert h["gold"] == "0"
    h2 = {"gold": "not-a-number"}
    gold_add(h2, 3)
    assert h2["gold"] == "3"
    h3 = {"gold": None}
    gold_add(h3, 1)
    assert h3["gold"] == "1"


# --- Items ---


def test_shop_and_equipment_bonuses():
    shop = shop_catalog()
    assert len(shop) >= 1
    for item in shop:
        assert int(item.get("price", 0)) > 0
    bare = equipment_bonuses(_hero())
    sword = equipment_bonuses(_hero(equipment_weapon="copper_sword"))
    assert sword["attack_power"] > bare["attack_power"]
    junk = equipment_bonuses(_hero(equipment_weapon="not_an_item"))
    assert junk["weapon_power"] == 0


# --- Chat ---


def test_sanitize_chat_adversarial():
    assert sanitize_chat(None) is None
    assert sanitize_chat("") is None
    assert sanitize_chat("   \t  ") is None
    assert sanitize_chat("\x00\x07hi") == "hi"
    assert sanitize_chat("  a   b  ") == "a b"
    assert sanitize_chat("hello\nworld") == "hello world"
    long = "z" * 500
    out = sanitize_chat(long)
    assert out is not None and len(out) == 200


# --- Engine registry ---


def test_combat_engine_start_end():
    combat_engine.end(99999)
    hero = _hero()
    b = combat_engine.start(99999, hero, "slime", seed=1)
    assert combat_engine.is_in_combat(99999)
    assert combat_engine.get(99999) is b
    combat_engine.mark_disconnected(99999, 0.0)
    assert 99999 in combat_engine.expired_grace() or combat_engine.grace_until.get(99999) is not None
    combat_engine.end(99999)
    assert not combat_engine.is_in_combat(99999)
